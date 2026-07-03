# Module Guide: API and Workers

Files in this guide (all complete — type them as-is):

- `backend/app/api/router.py`
- `backend/app/api/routes/health.py`
- `backend/app/api/routes/projects.py`
- `backend/app/api/routes/files.py`
- `backend/app/api/routes/papers.py`
- `backend/app/api/routes/jobs.py`
- `backend/app/api/routes/graph.py`
- `backend/app/api/routes/agent.py`
- `backend/app/api/routes/latex.py`
- `backend/app/workers/arq_app.py`
- `backend/app/workers/jobs.py`

**Why this module:** routes stay thin — validate HTTP, build a `ToolContext`, call the same tool/service functions the agent uses. Workers run everything slow (external APIs, embedding, graph sync, compilation) off the request path. The `jobs` table is the UI's source of truth; arq internals are an implementation detail the frontend never sees.

---

## `backend/app/api/router.py`

```python
from fastapi import APIRouter

from app.api.routes import agent, files, graph, health, jobs, latex, papers, projects

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(files.router, tags=["files"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(latex.router, prefix="/latex", tags=["latex"])
```

## `backend/app/api/routes/health.py`

Exercises each store with the cheapest real query; always 200 with a truthful body.

```python
from fastapi import APIRouter, Request
from sqlalchemy import text

from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.get("/health")
async def health(request: Request) -> dict:
    checks: dict[str, str] = {}

    try:
        async with request.app.state.db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        log.warning("health.postgres_failed", error=str(exc))
        checks["postgres"] = "error"

    try:
        await request.app.state.neo4j.execute_query("RETURN 1")
        checks["neo4j"] = "ok"
    except Exception as exc:
        log.warning("health.neo4j_failed", error=str(exc))
        checks["neo4j"] = "error"

    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        log.warning("health.redis_failed", error=str(exc))
        checks["redis"] = "error"

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, **checks}
```

## `backend/app/api/routes/projects.py`

Project creation bootstraps `main.tex` + `references.bib` at version 1. `ensure_dev_user` seeds the dev user idempotently on first use. Also serves the project's paper list (bibliography panel).

```python
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Paper, Project, ProjectFile, ProjectPaper, User
from app.deps import get_app_settings, get_db

router = APIRouter()

DEFAULT_MAIN_TEX = r"""\documentclass{article}
\usepackage{hyperref}
\usepackage{cite}

\title{Untitled Research Draft}
\author{}
\date{\today}

\begin{document}
\maketitle

\section{Introduction}
Start writing here.

\bibliographystyle{plain}
\bibliography{references}

\end{document}
"""


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


async def ensure_dev_user(session: AsyncSession, settings: Settings) -> User:
    user = await session.get(User, UUID(settings.DEV_USER_ID))
    if user is None:
        user = User(
            id=UUID(settings.DEV_USER_ID), email="dev@citepilot.local", display_name="Dev User"
        )
        session.add(user)
        await session.flush()
    return user


@router.get("")
async def list_projects(session: AsyncSession = Depends(get_db)) -> list[dict]:
    projects = (
        await session.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    user = await ensure_dev_user(session, settings)
    project = Project(user_id=user.id, name=body.name, description=body.description)
    session.add(project)
    await session.flush()
    session.add_all(
        [
            ProjectFile(project_id=project.id, path="main.tex", content=DEFAULT_MAIN_TEX, version=1),
            ProjectFile(project_id=project.id, path="references.bib", content="", version=1),
        ]
    )
    await session.commit()
    return {"id": str(project.id), "name": project.name, "description": project.description}


@router.get("/{project_id}/papers")
async def list_project_papers(
    project_id: UUID, session: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = (
        await session.execute(
            select(Paper, ProjectPaper.bibtex_key)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(ProjectPaper.added_at.desc())
        )
    ).all()
    return [
        {
            "paper_id": str(paper.id),
            "bibtex_key": bibtex_key,
            "title": paper.title,
            "year": paper.publication_year,
            "cited_by_count": paper.cited_by_count,
            "is_stub": paper.is_stub,
        }
        for paper, bibtex_key in rows
    ]
```

## `backend/app/api/routes/files.py`

The versioning policy, exactly: autosave (`explicit: false`) updates content in place; explicit save bumps the version and snapshots; stale `base_version` → 409 carrying the current state so the frontend can reload.

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileVersion, ProjectFile
from app.deps import get_db

router = APIRouter()


class FileUpdate(BaseModel):
    content: str
    base_version: int
    explicit: bool = False


@router.get("/projects/{project_id}/files")
async def list_files(project_id: UUID, session: AsyncSession = Depends(get_db)) -> list[dict]:
    files = (
        await session.execute(
            select(ProjectFile)
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.path)
        )
    ).scalars().all()
    return [
        {"id": str(f.id), "path": f.path, "content": f.content, "version": f.version}
        for f in files
    ]


@router.put("/projects/{project_id}/files/{file_id}")
async def update_file(
    project_id: UUID,
    file_id: UUID,
    body: FileUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict:
    file = await session.get(ProjectFile, file_id)
    if file is None or file.project_id != project_id:
        raise HTTPException(status_code=404, detail="file not found")
    if file.version != body.base_version:
        raise HTTPException(
            status_code=409,
            detail={"current_version": file.version, "current_content": file.content},
        )

    file.content = body.content
    if body.explicit:
        file.version += 1
        session.add(
            FileVersion(
                file_id=file.id, version=file.version, content=file.content, created_by="user"
            )
        )
    await session.commit()
    return {"id": str(file.id), "path": file.path, "version": file.version}
```

## `backend/app/api/routes/papers.py`

Thin wrappers over the core tools — one `ToolContext`, zero duplicated logic.

```python
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import ImportPaperInput, SearchPapersInput
from app.agent.tools import ToolContext, import_paper, search_papers
from app.config import Settings
from app.deps import get_app_settings, get_arq_pool, get_db, get_neo4j, get_redis

router = APIRouter()


def _ctx(session, settings, neo4j, redis, arq_pool) -> ToolContext:
    return ToolContext(session, settings, neo4j, redis, arq_pool)


@router.post("/search")
async def paper_search(
    body: SearchPapersInput,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    ctx = _ctx(session, settings, neo4j, redis, arq_pool)
    return (await search_papers(ctx, body)).model_dump(mode="json")


@router.post("/import")
async def paper_import(
    body: ImportPaperInput,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    ctx = _ctx(session, settings, neo4j, redis, arq_pool)
    return (await import_paper(ctx, body)).model_dump(mode="json")
```

## `backend/app/api/routes/jobs.py`

The generic polling endpoint — the frontend polls this while a job is non-terminal.

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.deps import get_db

router = APIRouter()


@router.get("/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_db)) -> dict:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "result": job.result,
        "error": job.error,
    }
```

## `backend/app/api/routes/graph.py`

Neighborhood for the graph panel + the "Enrich graph" button (promotes the most-referenced stubs).

```python
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.deps import get_arq_pool, get_db, get_neo4j
from app.graph.queries import two_hop_neighborhood

router = APIRouter()


@router.get("/neighborhood")
async def neighborhood(paper_id: UUID, per_hop: int = 15, neo4j=Depends(get_neo4j)) -> dict:
    return await two_hop_neighborhood(neo4j, str(paper_id), per_hop=per_hop)


class ExpandRequest(BaseModel):
    project_id: UUID
    top_n: int = Field(default=10, ge=1, le=25)


@router.post("/expand")
async def expand_graph(
    body: ExpandRequest,
    session: AsyncSession = Depends(get_db),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    job = Job(
        job_type="expand_citation_graph",
        input={"project_id": str(body.project_id), "top_n": body.top_n},
    )
    session.add(job)
    await session.commit()
    arq_job = await arq_pool.enqueue_job("expand_citation_graph_job", str(job.id))
    if arq_job is not None:
        job.queue_job_id = arq_job.job_id
        await session.commit()
    return {"job_id": str(job.id), "status": "queued"}
```

## `backend/app/api/routes/agent.py`

The streaming endpoint, done properly: an `asyncio.Queue` decouples the orchestrator (producer) from the HTTP response (consumer), so events reach the browser **as they happen** — collecting events into a list and yielding at the end would be a spinner, not a stream. FastAPI keeps `Depends(get_db)` open until the streamed response finishes, so the session stays valid.

Also here: session creation/history and the patch **accept** endpoint (the other half of guide 06's proposal flow).

```python
import asyncio
import contextlib
import json
from datetime import UTC, datetime
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm.providers import create_llm_client
from app.agent.orchestrator import AgentTurnContext, run_agent_turn
from app.agent.schemas import PatchLatexFileInput, ToolError
from app.agent.tool_registry import build_default_registry
from app.agent.tools import ToolContext, patch_latex_file
from app.api.routes.projects import ensure_dev_user
from app.config import Settings
from app.db.models import AgentMessage, AgentSession, Project, ToolCallRecord
from app.deps import get_app_settings, get_arq_pool, get_db, get_neo4j, get_redis
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


class AgentStreamRequest(BaseModel):
    project_id: UUID
    session_id: UUID | None = None
    message: str
    active_file_path: str | None = None
    selected_text: str | None = None


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: UUID, session: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await session.execute(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at)
        )
    ).scalars().all()
    return [
        {"id": str(m.id), "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in rows
    ]


@router.post("/stream")
async def stream_agent(
    body: AgentStreamRequest,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
):
    project = await session.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if body.session_id:
        agent_session = await session.get(AgentSession, body.session_id)
        if agent_session is None or agent_session.project_id != project.id:
            raise HTTPException(status_code=404, detail="agent session not found")
    else:
        user = await ensure_dev_user(session, settings)
        agent_session = AgentSession(
            project_id=project.id, user_id=user.id, title=body.message[:80]
        )
        session.add(agent_session)
        await session.commit()

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event_name: str, payload: dict) -> None:
        await queue.put(sse(event_name, payload))

    async def run() -> None:
        llm = create_llm_client(settings)
        try:
            ctx = ToolContext(session, settings, neo4j, redis, arq_pool)
            registry = build_default_registry(ctx)
            turn = AgentTurnContext(
                project_id=project.id,
                project_name=project.name,
                active_file_path=body.active_file_path,
                selected_text=body.selected_text,
                auto_apply_patches=False,
            )
            await run_agent_turn(
                session, agent_session.id, body.message, turn, registry, llm, emit
            )
        except Exception as exc:
            log.error("agent.stream.failed", session_id=str(agent_session.id), error=str(exc))
            await queue.put(sse("error", {"message": str(exc)}))
        finally:
            aclose = getattr(llm, "aclose", None)
            if aclose:
                await aclose()
            await queue.put(None)   # sentinel: stream is over

    task = asyncio.create_task(run())

    async def event_stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:                     # client disconnected or stream finished
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/patches/{tool_call_id}/accept")
async def accept_patch(
    tool_call_id: UUID,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    record = await session.get(ToolCallRecord, tool_call_id)
    if record is None or record.tool_name != "patch_latex_file":
        raise HTTPException(status_code=404, detail="patch proposal not found")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail=f"patch already {record.status}")

    ctx = ToolContext(session, settings, neo4j, redis, arq_pool)
    try:
        args = PatchLatexFileInput.model_validate(record.arguments)
        output = await patch_latex_file(ctx, args)
    except ToolError as exc:
        record.status = "failed"
        record.error = f"{exc.code}: {exc.message}"
        record.completed_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(status_code=422, detail=exc.as_tool_result())

    payload = output.model_dump(mode="json")
    record.status = "completed"
    record.result = payload
    record.completed_at = datetime.now(UTC)
    await session.commit()
    return payload
```

## `backend/app/api/routes/latex.py`

Compile goes through the same core tool (which enqueues the arq job); status polling and PDF streaming are plain reads. The PDF endpoint exists because the preview `<iframe>` needs a real URL, not JSON.

```python
from pathlib import Path
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import CompileLatexInput
from app.agent.tools import ToolContext, compile_latex
from app.config import Settings
from app.db.models import LatexCompilation
from app.deps import get_app_settings, get_arq_pool, get_db, get_neo4j, get_redis

router = APIRouter()


@router.post("/compile")
async def compile_route(
    body: CompileLatexInput,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    ctx = ToolContext(session, settings, neo4j, redis, arq_pool)
    return (await compile_latex(ctx, body)).model_dump(mode="json")


@router.get("/compilations/{compilation_id}")
async def get_compilation(
    compilation_id: UUID, session: AsyncSession = Depends(get_db)
) -> dict:
    compilation = await session.get(LatexCompilation, compilation_id)
    if compilation is None:
        raise HTTPException(status_code=404, detail="compilation not found")
    return {
        "id": str(compilation.id),
        "status": compilation.status,
        "logs": compilation.logs,
        "error": compilation.error,
        "has_pdf": bool(compilation.pdf_path),
    }


@router.get("/compilations/{compilation_id}/pdf")
async def get_pdf(compilation_id: UUID, session: AsyncSession = Depends(get_db)):
    compilation = await session.get(LatexCompilation, compilation_id)
    if compilation is None or not compilation.pdf_path:
        raise HTTPException(status_code=404, detail="pdf not found")
    path = Path(compilation.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="pdf artifact missing")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{compilation_id}.pdf",
        content_disposition_type="inline",
    )
```

## `backend/app/workers/arq_app.py` (replaces the bootstrap stub)

Worker deps are created **once** in `on_startup` and shared by all jobs via arq's `ctx` — same lifespan philosophy as the API process. `ctx["redis"]` is arq's own pool, used by jobs to enqueue follow-up jobs.

```python
from arq.connections import RedisSettings

from app.config import get_settings
from app.logging import configure_logging
from app.workers import jobs


async def startup(ctx: dict) -> None:
    configure_logging()
    ctx["deps"] = jobs.WorkerDeps()


async def shutdown(ctx: dict) -> None:
    await ctx["deps"].aclose()


class WorkerSettings:
    functions = [
        jobs.ingest_paper_job,
        jobs.expand_citation_graph_job,
        jobs.embed_chunks_job,
        jobs.compile_latex_job,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_jobs = 4
    job_timeout = 300
```

## `backend/app/workers/jobs.py`

The ingest job is the whole M4–M6 pipeline in one place: fetch → normalize → dedup upsert → stubs + edges → link to project → mirror to Neo4j → enqueue embedding. Note the order: **commit Postgres first, then mirror to Neo4j** — never mirror uncommitted state.

```python
from __future__ import annotations

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
                for stub in stubs:
                    work = await client.get_work(stub.openalex_id)
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
```

## Acceptance checks

1. All route modules import; `docker compose up` boots API + worker clean.
2. `POST /api/projects` → project with `main.tex` + `references.bib`; autosave doesn't bump versions, explicit save does, stale write → 409.
3. `POST /api/papers/import` (real OpenAlex ID) → job goes `queued → running → completed`; Postgres has the paper + stub rows + citation edges; Neo4j has the nodes + edges; `paper_chunks.embedding` fills in.
4. `POST /api/graph/expand` → stubs visibly promote.
5. `curl -N -X POST localhost:8000/api/agent/stream -H 'content-type: application/json' -d '{"project_id":"...","message":"say hi"}'` → events arrive **incrementally**, ending with `done`.
6. Compile → poll `/api/latex/compilations/{id}` → open `/pdf` in the browser.
