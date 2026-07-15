from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import GetPaperInput, ImportPaperInput, SearchPapersInput, ToolError
from app.agent.tools import ToolContext, get_paper, import_paper, search_papers
from app.config import Settings
from app.db.models import Paper, ProjectPaper
from app.deps import get_app_settings, get_arq_pool, get_db, get_neo4j, get_redis
from app.ingestion.bibtex import BibtexPaper, generate_fallback_bibtex

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


@router.get("/{paper_id}")
async def paper_detail(
    paper_id: UUID,
    project_id: UUID | None = None,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    """Full metadata for one paper, used by the graph detail panel.

    Includes the project bibtex_key and a rendered BibTeX entry when project_id
    is provided and the paper belongs to that project.
    """
    ctx = _ctx(session, settings, neo4j, redis, arq_pool)
    try:
        output = await get_paper(ctx, GetPaperInput(paper_id=paper_id, project_id=project_id))
    except ToolError as exc:
        raise HTTPException(status_code=404, detail=exc.message)

    detail = output.paper
    detail["bibtex_key"] = None
    detail["bibtex"] = None
    detail["url"] = None
    detail["pdf_url"] = None

    paper = await session.get(Paper, paper_id)
    if paper is not None:
        detail["url"] = paper.url
        detail["pdf_url"] = paper.pdf_url

    if project_id is not None:
        bibtex_key = (
            await session.execute(
                select(ProjectPaper.bibtex_key).where(
                    ProjectPaper.project_id == project_id,
                    ProjectPaper.paper_id == paper_id,
                )
            )
        ).scalar_one_or_none()
        if bibtex_key and paper is not None:
            detail["bibtex_key"] = bibtex_key
            detail["bibtex"] = generate_fallback_bibtex(
                bibtex_key,
                BibtexPaper(
                    title=paper.title,
                    publication_year=paper.publication_year,
                    venue_name=paper.venue_name,
                    doi=paper.doi,
                    url=paper.url,
                    authors=detail.get("authors", []),
                ),
            )

    return detail