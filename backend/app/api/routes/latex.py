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