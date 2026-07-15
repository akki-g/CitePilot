from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned_project, require_verified_user
from app.db.models import Citation, Job, Paper, ProjectPaper, User
from app.deps import get_arq_pool, get_db, get_neo4j
from app.graph.queries import two_hop_neighborhood

router = APIRouter()


@router.get("/neighborhood")
async def neighborhood(paper_id: UUID, per_hop: int = 15, neo4j=Depends(get_neo4j)) -> dict:
    return await two_hop_neighborhood(neo4j, str(paper_id), per_hop=per_hop)


@router.get("/project/{project_id}")
async def project_graph(
    project_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> dict:
    """Project papers plus their strongest shared foundations.

    Postgres is authoritative for this overview, so it stays fast and remains
    available while Neo4j is rebuilding. Showing only edges among project
    papers made most real bibliographies look disconnected; the capped related
    set reveals which external papers connect the project together.
    """
    await get_owned_project(session, user, project_id)
    rows = (
        await session.execute(
            select(Paper, ProjectPaper.bibtex_key)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(Paper.publication_year)
        )
    ).all()

    nodes = [
        {
            "id": str(paper.id),
            "title": paper.title,
            "year": paper.publication_year,
            "cited_by_count": paper.cited_by_count,
            "is_stub": paper.is_stub,
            "is_seed": False,
            "bibtex_key": bibtex_key,
            "in_project": True,
            "role": "project",
            "connection_count": 0,
        }
        for paper, bibtex_key in rows
    ]

    ids = [paper.id for paper, _ in rows]
    related_count = 0
    hidden_stubs = 0
    edges: list[dict] = []
    if ids:
        related_rows = (
            await session.execute(
                select(Paper, func.count(Citation.citing_paper_id).label("connection_count"))
                .join(Citation, Citation.cited_paper_id == Paper.id)
                .where(
                    Citation.citing_paper_id.in_(ids),
                    Paper.id.not_in(ids),
                    Paper.is_stub.is_(False),
                    Paper.title.is_not(None),
                )
                .group_by(Paper.id)
                .order_by(
                    func.count(Citation.citing_paper_id).desc(),
                    Paper.cited_by_count.desc(),
                )
                .limit(24)
            )
        ).all()
        nodes.extend(
            {
                "id": str(paper.id),
                "title": paper.title,
                "year": paper.publication_year,
                "cited_by_count": paper.cited_by_count,
                "is_stub": paper.is_stub,
                "is_seed": False,
                "bibtex_key": None,
                "in_project": False,
                "role": "foundation",
                "connection_count": connection_count,
            }
            for paper, connection_count in related_rows
        )
        related_count = len(related_rows)

        hidden_stubs = (
            await session.execute(
                select(func.count(func.distinct(Citation.cited_paper_id)))
                .join(Paper, Paper.id == Citation.cited_paper_id)
                .where(
                    Citation.citing_paper_id.in_(ids),
                    Paper.is_stub.is_(True),
                )
            )
        ).scalar_one()

        visible_ids = [UUID(node["id"]) for node in nodes]
        edge_rows = (
            await session.execute(
                select(Citation.citing_paper_id, Citation.cited_paper_id).where(
                    Citation.citing_paper_id.in_(ids),
                    Citation.cited_paper_id.in_(visible_ids),
                )
            )
        ).all()
        edges = [
            {"source": str(citing), "target": str(cited), "type": "CITES"}
            for citing, cited in edge_rows
        ]

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "project_papers": len(rows),
            "related_papers": related_count,
            "citation_links": len(edges),
            "hidden_stubs": hidden_stubs,
        },
    }


class ExpandRequest(BaseModel):
    project_id: UUID
    top_n: int = Field(default=10, ge=1, le=25)


@router.post("/expand")
async def expand_graph(
    body: ExpandRequest,
    session: AsyncSession = Depends(get_db),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    user: User = Depends(require_verified_user),
) -> dict:
    await get_owned_project(session, user, body.project_id)
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
