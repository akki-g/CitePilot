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