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