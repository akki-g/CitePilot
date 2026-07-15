from pathlib import Path
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import CompileLatexInput
from app.agent.tools import ToolContext, compile_latex
from app.auth.dependencies import get_owned_project, require_verified_user
from app.config import Settings
from app.db.models import LatexCompilation, Project, ProjectFile, User
from app.deps import get_app_settings, get_arq_pool, get_db, get_neo4j, get_redis

router = APIRouter()


def _compilation_payload(compilation: LatexCompilation) -> dict:
    return {
        "id": str(compilation.id),
        "status": compilation.status,
        "logs": compilation.logs,
        "error": compilation.error,
        "has_pdf": bool(compilation.pdf_path),
        "created_at": compilation.created_at.isoformat(),
        "completed_at": (
            compilation.completed_at.isoformat() if compilation.completed_at else None
        ),
    }


@router.post("/compile")
async def compile_route(
    body: CompileLatexInput,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    user: User = Depends(require_verified_user),
) -> dict:
    await get_owned_project(session, user, body.project_id)
    ctx = ToolContext(session, settings, neo4j, redis, arq_pool, user_id=user.id)
    return (await compile_latex(ctx, body)).model_dump(mode="json")


@router.get("/compilations/{compilation_id}")
async def get_compilation(
    compilation_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> dict:
    compilation = await session.scalar(
        select(LatexCompilation)
        .join(Project, Project.id == LatexCompilation.project_id)
        .where(LatexCompilation.id == compilation_id, Project.user_id == user.id)
    )
    if compilation is None:
        raise HTTPException(status_code=404, detail="compilation not found")
    return _compilation_payload(compilation)


@router.get("/projects/{project_id}/latest")
async def get_latest_compilation(
    project_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> dict:
    """Return the durable PDF preview and whether project sources changed afterward."""
    await get_owned_project(session, user, project_id)

    latest_successful = (
        await session.execute(
            select(LatexCompilation)
            .where(
                LatexCompilation.project_id == project_id,
                LatexCompilation.status == "completed",
                LatexCompilation.pdf_path.is_not(None),
            )
            .order_by(LatexCompilation.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    latest_attempt = (
        await session.execute(
            select(LatexCompilation)
            .where(LatexCompilation.project_id == project_id)
            .order_by(LatexCompilation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    source_updated_at = (
        await session.execute(
            select(func.max(ProjectFile.updated_at)).where(ProjectFile.project_id == project_id)
        )
    ).scalar_one_or_none()

    is_stale = latest_successful is None
    if latest_successful is not None and source_updated_at is not None:
        # created_at is the compile snapshot boundary. A file saved while the
        # worker is compiling must still mark that PDF as stale.
        is_stale = source_updated_at > latest_successful.created_at

    return {
        "compilation": (
            _compilation_payload(latest_successful) if latest_successful is not None else None
        ),
        "latest_attempt": (
            _compilation_payload(latest_attempt) if latest_attempt is not None else None
        ),
        "is_stale": is_stale,
        "source_updated_at": source_updated_at.isoformat() if source_updated_at else None,
    }


@router.get("/compilations/{compilation_id}/pdf")
async def get_pdf(
    compilation_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
):
    compilation = await session.scalar(
        select(LatexCompilation)
        .join(Project, Project.id == LatexCompilation.project_id)
        .where(LatexCompilation.id == compilation_id, Project.user_id == user.id)
    )
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
