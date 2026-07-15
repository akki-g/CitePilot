from __future__ import annotations

import httpx
from arq.connections import ArqRedis

from neo4j import AsyncDriver
from redis.asyncio import Redis

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import schemas as s
from app.agent.schemas import ToolError
from app.config import Settings
from app.db.models import (
    Author,
    Concept,
    Job,
    LatexCompilation,
    Paper,
    PaperAuthor,
    PaperConcept,
    Project,
    ProjectFile,
    ProjectPaper,
)
from app.graph import queries
from app.ingestion.bibtex import BibtexPaper, generate_fallback_bibtex, rekey_bibtex
from app.ingestion.crossref import CrossrefClient
from app.ingestion.normalize import normalize_openalex_work
from app.ingestion.openalex import OpenAlexClient
from app.ingestion.upsert import link_project_paper
from app.latex.patcher import PATCH_ADAPTER, PatchError, apply_patch
from app.latex.sanitizer import UnsafePathError, sanitize_project_path
from app.logging import get_logger
from app.retrieval.embeddings import EmbeddingRateLimitError, create_embedding_client
from app.retrieval.explain import RetrievalFeatures, render_reason
from app.retrieval.graph_search import GraphSearch
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_search import VectorSearch


log = get_logger(__name__)

class ToolContext: 
    """
    Runtime Dependencies every tool needs. FastAPI, the MCP server, and
    the worker each build one - tool logic never knows who is calling it
    """

    def __init__(
            self, 
            session: AsyncSession,
            settings: Settings,
            neo4j: AsyncDriver,
            redis: Redis,
            arq_pool: ArqRedis | None = None
    ):
        self.session = session
        self.settings = settings
        self.neo4j = neo4j
        self.redis = redis
        self.arq_pool = arq_pool


async def _require_project(ctx: ToolContext, project_id) -> Project:
    # fix: was `ctx.session.execute.get(...)` — .get is a method on the session itself,
    # not on execute; the old form raised AttributeError on every project-scoped tool
    project = await ctx.session.get(Project, project_id)
    if project is None:
        raise ToolError("not_found", f"Project {project_id} does not exist")
    return project

async def _author_names(ctx: ToolContext, paper_ids: list) -> dict:
    # Helper used by paper search/BibTeX tools to avoid duplicating author joins.
    if not paper_ids:
        return {}
    rows = (
        await ctx.session.execute(
            select(PaperAuthor.paper_id, Author.name)
            .join(Author, Author.id == PaperAuthor.author_id)
            .where(PaperAuthor.paper_id.in_(paper_ids))
            .order_by(PaperAuthor.author_order)
        )
    ).all()
    names: dict = {}
    for paper_id, name in rows:
        names.setdefault(paper_id, []).append(name)
    return names


async def search_papers(ctx: ToolContext, args: s.SearchPapersInput) -> s.SearchPapersOutput:

    results: list[s.PaperSearchResult] = []

    if args.source == "local":
        # local search is a simple title search for POC
        stmt = select(Paper).where(Paper.title.is_not(None), Paper.title.ilike(f"%{args.query}%"))
        if args.year_min: 
            stmt = stmt.where(Paper.publication_year >= args.year_min)
        if args.year_max:
            stmt = stmt.where(Paper.publication_year <= args.year_max)
        
        stmt = stmt.order_by(Paper.cited_by_count.desc()).limit(args.limit)
        papers = (await ctx.session.execute(stmt)).scalars().all()

        names = await _author_names(ctx, [p.id for p in papers])
        project_paper_ids: set = set()
        if args.project_id and papers:
            project_paper_ids = {
                row[0]
                for row in (
                    await ctx.session.execute(
                        select(ProjectPaper.paper_id).where(
                            ProjectPaper.project_id == args.project_id,
                            ProjectPaper.paper_id.in_([paper.id for paper in papers]),
                        )
                    )
                ).all()
            }
        for p in papers:
            results.append(
                s.PaperSearchResult(
                    paper_id=p.id,
                    external_id=p.openalex_id,
                    title=p.title,
                    year=p.publication_year,
                    authors=names.get(p.id, [])[:5],
                    abstract=(p.abstract or "")[:500] or None,
                    cited_by_count=p.cited_by_count or 0,
                    imported=p.id in project_paper_ids if args.project_id else not p.is_stub,
                )
            )
    else:
        # OpenAlex path hits the cached client, then normalizes results.
        client = OpenAlexClient(ctx.settings, ctx.redis)
        try:
            data = await client.search_works(args.query, limit=args.limit)
        finally:
            await client.aclose()
        normalized = [normalize_openalex_work(work) for work in data.get("results", [])]
        source_ids = [paper.source_id for paper in normalized]
        dois = [paper.doi for paper in normalized if paper.doi]
        existing_rows = []
        if source_ids or dois:
            conditions = [Paper.openalex_id.in_(source_ids)]
            if dois:
                conditions.append(Paper.doi.in_(dois))
            existing_rows = (
                await ctx.session.execute(select(Paper).where(or_(*conditions)))
            ).scalars().all()
        by_openalex = {paper.openalex_id: paper for paper in existing_rows if paper.openalex_id}
        by_doi = {paper.doi: paper for paper in existing_rows if paper.doi}

        project_paper_ids: set = set()
        if args.project_id and existing_rows:
            project_paper_ids = {
                row[0]
                for row in (
                    await ctx.session.execute(
                        select(ProjectPaper.paper_id).where(
                            ProjectPaper.project_id == args.project_id,
                            ProjectPaper.paper_id.in_([paper.id for paper in existing_rows]),
                        )
                    )
                ).all()
            }

        for np in normalized:
            if args.year_min and np.publication_year and np.publication_year < args.year_min:
                continue
            if args.year_max and np.publication_year and np.publication_year > args.year_max:
                continue
            existing = by_openalex.get(np.source_id) or (by_doi.get(np.doi) if np.doi else None)
            results.append(
                s.PaperSearchResult(
                    paper_id=existing.id if existing else None,
                    external_id=np.source_id,
                    title=np.title,
                    year=np.publication_year,
                    authors=[a.name for a in np.authors][:5],
                    abstract=(np.abstract or "")[:500] or None,
                    cited_by_count=np.cited_by_count or 0,
                    imported=(
                        existing.id in project_paper_ids
                        if args.project_id and existing
                        else bool(existing and not existing.is_stub) if not args.project_id else False
                    ),
                )
            )

    return s.SearchPapersOutput(
        papers=results,
        summary=f"found {len(results)} papers for '{args.query}' via {args.source}",
    )

async def import_paper(ctx: ToolContext, args: s.ImportPaperInput) -> s.ImportPaperOutput:
    # import is slow so the tools queues a job instead of doing work inline
    await _require_project(ctx, args.project_id)

    if ctx.arq_pool is None:
        raise ToolError("unavailable", "job queue is not available in this context")
    
    job = Job(
        job_type="ingest_paper",
        input={
            "source": args.source,
            "source_id": args.source_id,
            "project_id": str(args.project_id),
        },
    )
    ctx.session.add(job)
    await ctx.session.commit()

    arq_job = await ctx.arq_pool.enqueue_job("ingest_paper_job", str(job.id))
    if arq_job is not None:
        job.queue_job_id = arq_job.job_id
        await ctx.session.commit()

    log.info("paper.import.queued", job_id=str(job.id), source_id=args.source_id)
    return s.ImportPaperOutput(job_id=job.id, status="queued")

async def get_paper(ctx: ToolContext, args: s.GetPaperInput) -> s.GetPaperOutput:
    paper = await ctx.session.get(Paper, args.paper_id)
    if paper is None:
        raise ToolError("not_found", f"Paper {args.paper_id} does not exist")

    names = await _author_names(ctx, [paper.id])
    concepts = [
        row[0]
        for row in (
            await ctx.session.execute(
                select(Concept.name)
                .join(PaperConcept, PaperConcept.concept_id == Concept.id)
                .where(PaperConcept.paper_id == paper.id)
            )
        ).all()
    ]
    in_project = False
    if args.project_id:
        in_project = (
            await ctx.session.execute(
                select(ProjectPaper).where(
                    ProjectPaper.project_id == args.project_id,
                    ProjectPaper.paper_id == paper.id,
                )
            )
        ).scalar_one_or_none() is not None

    return s.GetPaperOutput(
        paper={
            "paper_id": str(paper.id),
            "openalex_id": paper.openalex_id,
            "doi": paper.doi,
            "title": paper.title,
            "abstract": paper.abstract,
            "year": paper.publication_year,
            "venue": paper.venue_name,
            "cited_by_count": paper.cited_by_count,
            "is_stub": paper.is_stub,
            "authors": names.get(paper.id, []),
            "concepts": concepts,
            "in_project": in_project,
        },
        summary=f"loaded paper: {paper.title or paper.openalex_id or paper.id}",
    )

async def get_citation_neighborhood(
    ctx: ToolContext, args: s.CitationNeighborhoodInput
) -> s.CitationNeighborhoodOutput:
    seed = str(args.paper_id)
    neighborhood = await queries.two_hop_neighborhood(ctx.neo4j, seed, per_hop=args.per_hop)

    candidates = list(await queries.co_citation(ctx.neo4j, [seed], limit=10))
    candidates += await queries.bibliographic_coupling(ctx.neo4j, [seed], limit=10)
    if args.include_shared_concepts:
        candidates += await queries.shared_concepts(ctx.neo4j, [seed], limit=10)

    merged: dict[str, dict] = {}
    for cand in candidates:
        entry = merged.setdefault(
            cand.paper_id, {"signals": [], "features": {}, "score": 0.0}
        )
        entry["signals"].append(cand.signal)
        entry["features"].update(cand.features)
        entry["score"] += cand.score

    ranked_neighbors = []
    for paper_id, entry in sorted(merged.items(), key=lambda kv: -kv[1]["score"])[:10]:
        features = RetrievalFeatures(
            retrieval_sources=entry["signals"],
            shared_reference_count=entry["features"].get("shared_reference_count", 0),
            co_citation_count=entry["features"].get("co_citation_count", 0),
            shared_concept_names=tuple(entry["features"].get("shared_concept_names", ())),
        )
        ranked_neighbors.append(
            {"paper_id": paper_id, "signals": entry["signals"], "reason": render_reason(features)}
        )

    return s.CitationNeighborhoodOutput(
        nodes=neighborhood["nodes"],
        edges=neighborhood["edges"],
        ranked_neighbors=ranked_neighbors,
        summary=(
            f"neighborhood has {len(neighborhood['nodes'])} papers, "
            f"{len(neighborhood['edges'])} citation edges"
        ),
    )


async def retrieve_evidence(
    ctx: ToolContext, args: s.RetrieveEvidenceInput
) -> s.RetrieveEvidenceOutput:
    # This is the tool surface over the HybridRetriever from guide 04.
    await _require_project(ctx, args.project_id)
    # redis-backed cache: repeat embeds of the same paragraph within a tool
    # loop stay off the provider's rate limit
    embeddings = create_embedding_client(ctx.settings, redis=ctx.redis)
    try:
        retriever = HybridRetriever(
            embeddings=embeddings,
            vector_store=VectorSearch(ctx.session),
            graph=GraphSearch(ctx.neo4j),
            session=ctx.session,
        )
        results = await retriever.retrieve(
            project_id=args.project_id,
            query=args.query,
            seed_paper_ids=args.seed_paper_ids,
            limit=args.limit,
        )
    except EmbeddingRateLimitError as exc:
        # surface throttling as a tool error the model can relay, instead of
        # an unhandled exception that kills the whole SSE stream
        raise ToolError("rate_limited", str(exc))
    except httpx.HTTPStatusError as exc:
        raise ToolError(
            "embedding_failed",
            f"embedding provider error ({exc.response.status_code}); retrieval is unavailable right now",
        )
    finally:
        aclose = getattr(embeddings, "aclose", None)
        if aclose:
            await aclose()

    evidence = [
        s.EvidenceItem(
            paper_id=r.paper_id,
            title=r.title,
            chunk_id=r.chunk_id,
            text=r.text,
            score=r.score,
            retrieval_sources=r.retrieval_sources,
            reason=r.reason,
            in_project=r.in_project,
            is_stub=r.is_stub,
        )
        for r in results
    ]
    sources = sorted({src for e in evidence for src in e.retrieval_sources})
    return s.RetrieveEvidenceOutput(
        evidence=evidence,
        summary=f"found {len(evidence)} candidate papers via {', '.join(sources) or 'no signals'}",
    )


async def rank_related_work(
    ctx: ToolContext, args: s.RankRelatedWorkInput
) -> s.RankRelatedWorkOutput:
    evidence_out = await retrieve_evidence(
        ctx,
        s.RetrieveEvidenceInput(
            project_id=args.project_id, query=args.section_text, limit=args.limit
        ),
    )
    paper_ids = [e.paper_id for e in evidence_out.evidence]
    key_rows = (
        await ctx.session.execute(
            select(ProjectPaper.paper_id, ProjectPaper.bibtex_key).where(
                ProjectPaper.project_id == args.project_id,
                ProjectPaper.paper_id.in_(paper_ids or [args.project_id]),
            )
        )
    ).all()
    keys = {paper_id: key for paper_id, key in key_rows}

    recommendations = [
        s.RelatedWorkRecommendation(
            paper_id=e.paper_id,
            bibtex_key=keys.get(e.paper_id),
            title=e.title,
            reason=e.reason,
            evidence_snippets=[e.text[:300]] if e.text else [],
            score=e.score,
            is_stub=e.is_stub,
        )
        for e in evidence_out.evidence
    ]
    return s.RankRelatedWorkOutput(
        recommendations=recommendations,
        summary=f"ranked {len(recommendations)} candidate citations",
    )


async def suggest_bibtex(ctx: ToolContext, args: s.SuggestBibtexInput) -> s.SuggestBibtexOutput:
    await _require_project(ctx, args.project_id)
    entries: list[s.BibtexEntry] = []
    crossref = CrossrefClient(ctx.settings, ctx.redis)
    try:
        for paper_id in args.paper_ids:
            paper = await ctx.session.get(Paper, paper_id)
            if paper is None:
                raise ToolError("not_found", f"Paper {paper_id} does not exist")
            if paper.is_stub:
                raise ToolError(
                    "is_stub",
                    f"Paper {paper_id} is a stub with incomplete metadata. Import it first.",
                )
            key = await link_project_paper(ctx.session, args.project_id, paper)

            bibtex = None
            if paper.doi:
                bibtex = await crossref.get_bibtex(paper.doi)   # publisher-quality, preferred
                if bibtex:
                    bibtex = rekey_bibtex(bibtex.strip() + "\n", key)
            if bibtex is None:                                   # fallback: generate + escape
                names = await _author_names(ctx, [paper.id])
                bibtex = generate_fallback_bibtex(
                    key,
                    BibtexPaper(
                        title=paper.title,
                        publication_year=paper.publication_year,
                        venue_name=paper.venue_name,
                        doi=paper.doi,
                        url=paper.url,
                        authors=names.get(paper.id, []),
                    ),
                )
            entries.append(s.BibtexEntry(paper_id=paper.id, bibtex_key=key, bibtex=bibtex))
    finally:
        await crossref.aclose()

    await ctx.session.commit()   # persist any new project_papers links
    return s.SuggestBibtexOutput(
        entries=entries, summary=f"prepared {len(entries)} BibTeX entries"
    )


async def inspect_latex_project(
    ctx: ToolContext, args: s.InspectLatexProjectInput
) -> s.InspectLatexProjectOutput:
    await _require_project(ctx, args.project_id)
    stmt = select(ProjectFile).where(ProjectFile.project_id == args.project_id)
    if args.paths:
        try:
            safe = [sanitize_project_path(p) for p in args.paths]
        except UnsafePathError as exc:
            raise ToolError("unsafe_path", str(exc))
        stmt = stmt.where(ProjectFile.path.in_(safe))
    files = (await ctx.session.execute(stmt.order_by(ProjectFile.path))).scalars().all()
    return s.InspectLatexProjectOutput(
        files=[
            s.LatexFileView(path=f.path, content=f.content, version=f.version) for f in files
        ],
        summary=f"read {len(files)} files: {', '.join(f.path for f in files)}",
    )


async def patch_latex_file(
    ctx: ToolContext, args: s.PatchLatexFileInput
) -> s.PatchLatexFileOutput:
    """Direct application — used by MCP and by the web accept endpoint. The web
    orchestrator intercepts this tool and turns it into a proposal instead."""
    await _require_project(ctx, args.project_id)
    try:
        # Validate dict into ReplaceTextPatch or InsertAfterPatch.
        patch = PATCH_ADAPTER.validate_python(args.patch)
    except Exception as exc:
        raise ToolError("invalid_arguments", f"patch failed validation: {exc}")
    try:
        result = await apply_patch(ctx.session, args.project_id, patch)
    except PatchError as exc:
        raise ToolError(exc.code, exc.message, exc.details)
    return s.PatchLatexFileOutput(
        status=result["status"],
        new_version=result["new_version"],
        summary=f"applied patch to {result['path']} -> version {result['new_version']}",
    )


async def compile_latex(ctx: ToolContext, args: s.CompileLatexInput) -> s.CompileLatexOutput:
    # Compilation is slow and sandboxed in worker, so enqueue it.
    await _require_project(ctx, args.project_id)
    if ctx.arq_pool is None:
        raise ToolError("unavailable", "job queue is not available in this context")
    try:
        safe_main = sanitize_project_path(args.main_file_path)
    except UnsafePathError as exc:
        raise ToolError("unsafe_path", str(exc))

    compilation = LatexCompilation(project_id=args.project_id, main_file_path=safe_main)
    ctx.session.add(compilation)
    await ctx.session.commit()
    await ctx.arq_pool.enqueue_job("compile_latex_job", str(compilation.id))
    log.info("latex.compile.queued", compilation_id=str(compilation.id))
    return s.CompileLatexOutput(compilation_id=compilation.id, status="queued")
