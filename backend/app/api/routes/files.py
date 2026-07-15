from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileVersion, Project, ProjectFile
from app.deps import get_db
from app.latex.sanitizer import UnsafePathError, sanitize_project_path

router = APIRouter()


class FileUpdate(BaseModel):
    content: str
    base_version: int
    explicit: bool = False


class FileImportItem(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=1_000_000)


class FileImportRequest(BaseModel):
    files: list[FileImportItem] = Field(min_length=1, max_length=30)
    overwrite: bool = False


IMPORTABLE_SUFFIXES = {".tex", ".bib", ".sty", ".cls", ".txt"}
MAX_IMPORT_BYTES = 2_000_000


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


@router.post("/projects/{project_id}/files/import")
async def import_files(
    project_id: UUID,
    body: FileImportRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Import browser-selected text assets into a LaTeX project in one request."""
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    total_bytes = sum(len(item.content.encode("utf-8")) for item in body.files)
    if total_bytes > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="selected files exceed the 2 MB import limit")

    sanitized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in body.files:
        try:
            path = sanitize_project_path(item.path)
        except UnsafePathError as exc:
            raise HTTPException(status_code=422, detail=f"invalid path '{item.path}': {exc}")
        if PurePosixPath(path).suffix.lower() not in IMPORTABLE_SUFFIXES:
            raise HTTPException(
                status_code=422,
                detail=f"unsupported file type for '{path}'",
            )
        if path in seen:
            raise HTTPException(status_code=422, detail=f"duplicate path '{path}'")
        seen.add(path)
        sanitized.append((path, item.content))

    existing = {
        file.path: file
        for file in (
            await session.execute(
                select(ProjectFile).where(
                    ProjectFile.project_id == project_id,
                    ProjectFile.path.in_([path for path, _ in sanitized]),
                )
            )
        ).scalars()
    }
    imported: list[ProjectFile] = []
    skipped: list[str] = []
    for path, content in sanitized:
        file = existing.get(path)
        if file is not None and not body.overwrite:
            skipped.append(path)
            continue
        if file is None:
            file = ProjectFile(project_id=project_id, path=path, content=content, version=1)
            session.add(file)
        else:
            file.content = content
            file.version += 1
            session.add(
                FileVersion(
                    file_id=file.id,
                    version=file.version,
                    content=content,
                    created_by="user",
                )
            )
        imported.append(file)

    await session.commit()
    return {
        "imported": [
            {"id": str(file.id), "path": file.path, "content": file.content, "version": file.version}
            for file in imported
        ],
        "skipped": skipped,
    }
