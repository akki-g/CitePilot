# base_version must match (stale patches are rejected, thats the concurrency safety net)
# the anchor must occur exactly once, failures never mutate anything, successes bumps the version
# and snapshots to file_version with created_by='agent' (undo story for AI edits)

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FileVersion, ProjectFile
from app.latex.sanitizer import sanitize_project_path

from app.logging import get_logger


log = get_logger(__name__)


class ReplaceTextPatch(BaseModel):
    # replace exact old_text with new_text

    operation: Literal["replace_text"]
    path: str
    base_version: int
    old_text: str       # must occur exactly once in the file
    new_text: str

class InsertAfterPatch(BaseModel):
    # insert new text immediately after a unique anchor
    operation: Literal["insert_after"]
    path: str
    # fix: base_version was missing — _check_version reads patch.base_version, so every
    # insert_after patch raised AttributeError (and skipped the stale-patch safety net)
    base_version: int
    anchor_text: str
    new_text: str

Patch = ReplaceTextPatch | InsertAfterPatch

PATCH_ADAPTER: TypeAdapter[Patch] = TypeAdapter(Patch)

class PatchError(Exception):
    """
    structured error designed for a model reader - the agent loop 
    feeds these back into the conversation so the model can retry
    """

    def __init__(self, code:str, message:str, details: dict | None = None):
        super().__init__(message)

        self.code = code
        self.message = message
        # fix: was `self.details = details`, leaving details as None when omitted;
        # consumers treat details as a dict
        self.details = details or {}



async def _load_file(session: AsyncSession, project_id: UUID, path: str) -> ProjectFile:
    # sanitize before querying
    safe_path = sanitize_project_path(path)

    file = (
        await session.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id, ProjectFile.path == safe_path
            )
        )
    ).scalar_one_or_none()

    if file is None:
        # fix: error code was "file not found" — codes are machine-readable, keep snake_case
        raise PatchError("file_not_found", f"No project file at path '{safe_path}'")

    return file

def _anchor_of(patch: Patch) -> str:
    # Normalize the two patch shapes into "the text that must be unique".
    return patch.old_text if isinstance(patch, ReplaceTextPatch) else patch.anchor_text


def _apply_to_content(content: str, patch: Patch) -> str:
    # count exact occurrences exactness is the safety mechanism
    anchor = _anchor_of(patch)
    occurrences = content.count(anchor)

    if occurrences == 0:
        # nothing changes; the agent should reread the file
        raise PatchError(
            "anchor_not_found",
            "Anchor text does not occur in file. Reread the file and retry"
            "with the exact current text",
            {"occurrences": 0}
        )
    
    if occurrences > 1:
        # ambiguous anchors would corrupt the wrong location so fail loudly
        raise PatchError(
            "anchor_ambiguous",
            f"Anchor text occurs {occurrences} times. Retry with a longer, unique anchor.",
            {"occurrences": occurrences},
        )
    
    if isinstance(patch, ReplaceTextPatch):
        # Replace the single exact match.
        return content.replace(anchor, patch.new_text, 1)
    # Insert after the single exact match.
    return content.replace(anchor, anchor + patch.new_text, 1)


def preview_patch_content(content: str, patch: Patch) -> str:
    """Apply the exact-anchor rules to in-memory content without persistence."""
    return _apply_to_content(content, patch)


def _check_version(file: ProjectFile, patch: Patch) -> None:
    # Reject stale patches built against old file contents.
    if patch.base_version != file.version:
        raise PatchError(
            "stale_version",
            f"File is at version {file.version}, patch was built against "
            f"{patch.base_version}. Re-read the file and rebuild the patch.",
            {"current_version": file.version},
        )
    

async def preview_patch(session: AsyncSession, project_id: UUID, patch: Patch) -> dict:
    """Compute before/after WITHOUT applying — powers the patch_proposal event
    that the UI shows for user approval."""
    file = await _load_file(session, project_id, patch.path)
    # Preview still checks version/anchor so the UI preview is trustworthy.
    _check_version(file, patch)
    return {
        "path": file.path,
        "before": file.content,
        "after": _apply_to_content(file.content, patch),
    }


async def apply_patch(session: AsyncSession, project_id: UUID, patch: Patch) -> dict:
    # load and validate before mutating anything    
    file = await _load_file(session, project_id, patch.path)
    _check_version(file, patch)
    new_content = _apply_to_content(file.content, patch) # raises before any mutation

    file.content = new_content
    # fix: was `file_version += 1` (undefined name, NameError) — the file row's version must bump
    file.version += 1
    # snapshot is the undo/audit story for AI edits
    session.add(
        FileVersion(
            file_id=file.id,
            version=file.version,
            content=new_content,
            created_by="agent",
        )
    )

    await session.commit()

    log.info(
        "latex.patch.applied",
        project_id=str(project_id),
        path=file.path,
        new_version=file.version,
    )

    return {"status": "applied", "path": file.path, "new_version": file.version}


# base_version prevents applying an edit to a file that changed since the agent read it
# exact once anchors prevent silent wrong location edits
# preview_patch() powers human approval in web UI
# apply patch is direct for MCP use, where versioning is the safety net
