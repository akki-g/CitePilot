from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned_project, require_verified_user
from app.db.models import Job, User
from app.deps import get_db

router = APIRouter()


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> dict:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    project_id = job.input.get("project_id") if isinstance(job.input, dict) else None
    if not project_id:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        await get_owned_project(session, user, UUID(project_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "result": job.result,
        "error": job.error,
    }
