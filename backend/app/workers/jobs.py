from __future__ import annotations

import asyncio
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Citation, Job, LatexCompilation, Paper, PaperChunk, ProjectPaper
from app.db.postgres import create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver
from app.graph.sync import sync_citations, sync_paper, sync_stub_papers
from app.ingestion.normalize import normalize_openalex_work
from app.ingestion.openalex import OpenAlexClient
from app.ingestion.upsert import ingest_normalized_paper, link_project_paper
from app.latex.compiler import compile_project
from app.logging import get_logger
from app.retrieval.embeddings import create_embedding_client

log = get_logger(__name__)


class WorkerDeps:
    def __init__(self):
        self.settings = get_settings()
        self.engine = create_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)
        self.neo4j = create_neo4j_driver(self.settings)
        self.redis = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)

    async def aclose(self) -> None:
        await self.redis.aclose()
        await self.neo4j.close()
        await self.engine.dispose()


async def _mark_job_failed(deps: WorkerDeps, job_id: UUID, error: str) -> None:
    async with deps.session_factory() as session:   # fresh session: the old one may be poisoned
        job = await session.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.error = error[:2000]
            await session.commit()


async def ingest_paper_job(ctx: dict, job_id: str) -> None:
    deps: WorkerDeps = ctx["deps"]
    jid = UUID(job_id)
    try:
        async with deps.session_factory() as session:
            job = await session.get(Job, jid)
            if job is None:
                return
            job.status = "running"
            await session.commit()
            log.info("paper.import.started", job_id=job_id)

            source_id = job.input["source_id"]
            project_id = UUID(job.input["project_id"])

            client = OpenAlexClient(deps.settings, deps.redis)
            try:
                work = await client.get_work(source_id)
            finally:
                await client.aclose()

            np = normalize_openalex_work(work)
            paper, cited = await ingest_normalized_paper(session, np)
            bibtex_key = await link_project_paper(session, project_id, paper)
            await session.commit()

            await sync_paper(session, deps.neo4j, paper.id)
            await sync_stub_papers(deps.neo4j, cited)
            await sync_citations(deps.neo4j, paper.id, [c.id for c in cited])

            await ctx["redis"].enqueue_job("embed_chunks_job", str(paper.id))

            job.status = "completed"
            job.result = {
                "paper_id": str(paper.id),
                "bibtex_key": bibtex_key,
                "references": len(cited),
            }
            await session.commit()
            log.info("paper.import.completed", job_id=job_id, paper_id=str(paper.id))
    except Exception as exc:
        log.error("paper.import.failed", job_id=job_id, error=str(exc))
        await _mark_job_failed(deps, jid, str(exc))


async def expand_citation_graph_job(ctx: dict, job_id: str) -> None:
    """Promote the most-referenced stubs in the project's neighborhood to full
    papers — the 'Enrich graph' button. The graph visibly densifies."""
    deps: WorkerDeps = ctx["deps"]
    jid = UUID(job_id)
    try:
        async with deps.session_factory() as session:
            job = await session.get(Job, jid)
            if job is None:
                return
            job.status = "running"
            await session.commit()

            project_id = UUID(job.input["project_id"])
            top_n = int(job.input.get("top_n", 10))

            stubs = (
                await session.execute(
                    select(Paper)
                    .join(Citation, Citation.cited_paper_id == Paper.id)
                    .join(ProjectPaper, ProjectPaper.paper_id == Citation.citing_paper_id)
                    .where(
                        ProjectPaper.project_id == project_id,
                        Paper.is_stub.is_(True),
                        Paper.openalex_id.is_not(None),
                    )
                    .group_by(Paper.id)
                    .order_by(func.count(Citation.citing_paper_id).desc())
                    .limit(top_n)
                )
            ).scalars().all()

            promoted: list[str] = []
            client = OpenAlexClient(deps.settings, deps.redis)
            try:
                # OpenAlex fetches dominate enrichment time. Keep database and
                # graph writes ordered, but overlap a small, polite number of
                # independent network requests.
                semaphore = asyncio.Semaphore(5)

                async def fetch_work(stub: Paper) -> tuple[Paper, dict]:
                    async with semaphore:
                        return stub, await client.get_work(stub.openalex_id)

                fetched = await asyncio.gather(*(fetch_work(stub) for stub in stubs))
                for stub, work in fetched:
                    np = normalize_openalex_work(work)
                    paper, cited = await ingest_normalized_paper(session, np)
                    await session.commit()
                    await sync_paper(session, deps.neo4j, paper.id)
                    await sync_stub_papers(deps.neo4j, cited)
                    await sync_citations(deps.neo4j, paper.id, [c.id for c in cited])
                    await ctx["redis"].enqueue_job("embed_chunks_job", str(paper.id))
                    promoted.append(str(paper.id))
            finally:
                await client.aclose()

            job.status = "completed"
            job.result = {"promoted": promoted}
            await session.commit()
            log.info("graph.expand.completed", job_id=job_id, promoted=len(promoted))
    except Exception as exc:
        log.error("graph.expand.failed", job_id=job_id, error=str(exc))
        await _mark_job_failed(deps, jid, str(exc))


async def embed_chunks_job(ctx: dict, paper_id: str) -> None:
    """Fire-and-forget follow-up to ingest: embed chunks with null embeddings,
    in batches of <= 64, stamping which model produced each vector."""
    deps: WorkerDeps = ctx["deps"]
    try:
        async with deps.session_factory() as session:
            chunks = (
                await session.execute(
                    select(PaperChunk).where(
                        PaperChunk.paper_id == UUID(paper_id),
                        PaperChunk.embedding.is_(None),
                    )
                )
            ).scalars().all()
            if not chunks:
                return

            embeddings = create_embedding_client(deps.settings)
            try:
                for start in range(0, len(chunks), 64):
                    batch = chunks[start : start + 64]
                    vectors = await embeddings.embed_texts([c.text for c in batch])
                    for chunk, vector in zip(batch, vectors):
                        chunk.embedding = vector
                        chunk.chunk_metadata = {
                            **chunk.chunk_metadata,
                            "embedding_model": deps.settings.EMBEDDING_MODEL or "fake",
                        }
            finally:
                aclose = getattr(embeddings, "aclose", None)
                if aclose:
                    await aclose()
            await session.commit()
            log.info("embed.completed", paper_id=paper_id, chunks=len(chunks))
    except Exception as exc:
        log.error("embed.failed", paper_id=paper_id, error=str(exc))
        raise   # let arq record the failure and retry


async def compile_latex_job(ctx: dict, compilation_id: str) -> None:
    deps: WorkerDeps = ctx["deps"]
    async with deps.session_factory() as session:
        compilation = await session.get(LatexCompilation, UUID(compilation_id))
        if compilation is None:
            return
        await compile_project(   # handles its own status transitions and errors
            session,
            deps.settings,
            compilation.project_id,
            compilation.main_file_path,
            compilation.id,
        )
