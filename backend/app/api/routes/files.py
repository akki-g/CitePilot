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

