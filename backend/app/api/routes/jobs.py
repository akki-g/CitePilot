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