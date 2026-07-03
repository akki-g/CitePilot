# Module Guide: LaTeX

Files in this guide (all complete — type them as-is):

- `backend/app/latex/sanitizer.py`
- `backend/app/latex/patcher.py` ⭐ core learning file
- `backend/app/latex/compiler.py`
- final `infra/docker/worker.Dockerfile`

**Why this module:** these are the agent's *write* actions, so the design goal is converting silent corruption into loud, recoverable failure. Patches are **anchor-based** because LLMs cannot count character offsets — a wrong offset corrupts a file silently, a wrong anchor fails with a structured error the agent can retry. Compilation is sandboxed: no shell escape, timeout, size cap, temp dirs.

**Comment style:** this guide has extra inline comments on every safety check, because those checks are the point of the module.

---

## `backend/app/latex/sanitizer.py`

Applied to every path from users, the agent, and the compiler. Project file paths are logical, not host paths.

```python
# Regex checks allowed characters for project-relative paths.
import re
# PurePosixPath parses logical project paths consistently across operating systems.
from pathlib import PurePosixPath

# Allow ordinary repo/project file names. No spaces keeps URL/path handling simple.
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class UnsafePathError(ValueError):
    # Specific exception type lets routes/tools convert path failures into clean errors.
    pass


def sanitize_project_path(path: str) -> str:
    # Null bytes are a classic filesystem attack/input-corruption vector.
    if "\x00" in path:
        raise UnsafePathError("path contains null byte")
    # Backslashes behave differently on Windows and can hide traversal intent.
    if "\\" in path:
        raise UnsafePathError("backslashes are not allowed")
    # Project files must be relative, never absolute host paths.
    if path.startswith("/"):
        raise UnsafePathError("absolute paths are not allowed")
    # Reject unsupported characters before normalizing.
    if not SAFE_PATH_RE.match(path):
        raise UnsafePathError("path contains unsupported characters")

    # Parse as POSIX path because project paths are logical, not OS-native.
    pure = PurePosixPath(path)
    # Empty/current/parent segments can create ambiguous or escaping paths.
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise UnsafePathError("empty, current, or parent path segments are not allowed")
    # Hidden files like `.env` should never be exposed to the agent/compiler.
    if any(part.startswith(".") for part in pure.parts):
        raise UnsafePathError("hidden files are not allowed")
    # Return normalized string form for DB/file lookup.
    return str(pure)
```

Walkthrough:

- The sanitizer is used by file CRUD, inspect tools, patch tools, and compiler writes.
- It protects both the host filesystem and project boundaries.
- It intentionally accepts a small path language so future behavior is predictable.

## ⭐ `backend/app/latex/patcher.py`

Rules: `base_version` must match (stale patches are rejected — that's the concurrency safety net), the anchor must occur **exactly once**, failures never mutate anything, success bumps the version and snapshots to `file_versions` with `created_by='agent'` (the undo story for AI edits).

```python
# Future annotations help union type hints.
from __future__ import annotations

# Literal restricts patch operation names to exact strings.
from typing import Literal
# UUID identifies project/file rows.
from uuid import UUID

# BaseModel validates patch JSON from the LLM/API.
from pydantic import BaseModel
# select loads files by project/path.
from sqlalchemy import select
# AsyncSession is the current DB unit of work.
from sqlalchemy.ext.asyncio import AsyncSession

# ORM rows updated by patch application.
from app.db.models import FileVersion, ProjectFile
# Every patch path goes through the sanitizer.
from app.latex.sanitizer import sanitize_project_path
# Structured logging for applied patches.
from app.logging import get_logger

# Module logger.
log = get_logger(__name__)


class ReplaceTextPatch(BaseModel):
    # Replace exact old_text with new_text.
    operation: Literal["replace_text"]
    path: str
    base_version: int
    old_text: str          # must occur EXACTLY ONCE in the file
    new_text: str


class InsertAfterPatch(BaseModel):
    # Insert new text immediately after a unique anchor.
    operation: Literal["insert_after"]
    path: str
    base_version: int
    anchor_text: str       # must occur EXACTLY ONCE
    new_text: str


Patch = ReplaceTextPatch | InsertAfterPatch


class PatchError(Exception):
    """Structured error designed for a model reader — the agent loop feeds
    these back into the conversation so the model can retry."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        # Exception message is human/model-readable.
        super().__init__(message)
        # Stable machine-readable error code for tool/UI handling.
        self.code = code
        self.message = message
        self.details = details or {}


async def _load_file(session: AsyncSession, project_id: UUID, path: str) -> ProjectFile:
    # Sanitize before querying so unsafe paths never touch DB/filesystem logic.
    safe_path = sanitize_project_path(path)
    file = (
        await session.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id, ProjectFile.path == safe_path
            )
        )
    ).scalar_one_or_none()
    if file is None:
        # ToolError-like failure tells the agent to inspect available files.
        raise PatchError("file_not_found", f"No project file at path '{safe_path}'.")
    return file


def _anchor_of(patch: Patch) -> str:
    # Normalize the two patch shapes into "the text that must be unique".
    return patch.old_text if isinstance(patch, ReplaceTextPatch) else patch.anchor_text


def _apply_to_content(content: str, patch: Patch) -> str:
    # Count exact occurrences. Exactness is the safety mechanism.
    anchor = _anchor_of(patch)
    occurrences = content.count(anchor)
    if occurrences == 0:
        # Nothing changes; the agent should re-read the file.
        raise PatchError(
            "anchor_not_found",
            "Anchor text does not occur in the file. Re-read the file and retry "
            "with the exact current text.",
            {"occurrences": 0},
        )
    if occurrences > 1:
        # Ambiguous anchors would corrupt the wrong location, so fail loudly.
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
    # Load and validate before mutating anything.
    file = await _load_file(session, project_id, patch.path)
    _check_version(file, patch)
    new_content = _apply_to_content(file.content, patch)   # raises before any mutation

    # Only after all checks pass do we mutate current content.
    file.content = new_content
    # Agent patches always bump version.
    file.version += 1
    # Snapshot is the undo/audit story for AI edits.
    session.add(
        FileVersion(
            file_id=file.id,
            version=file.version,
            content=new_content,
            created_by="agent",
        )
    )
    await session.commit()
    # Log after commit so logs reflect durable state.
    log.info(
        "latex.patch.applied",
        project_id=str(project_id),
        path=file.path,
        new_version=file.version,
    )
    return {"status": "applied", "path": file.path, "new_version": file.version}
```

Patch walkthrough:

- `base_version` prevents applying an edit to a file that changed since the agent read it.
- Exact-once anchors prevent silent wrong-location edits.
- `preview_patch()` powers human approval in the web UI.
- `apply_patch()` is direct for MCP use, where versioning is the safety net.

## `backend/app/latex/compiler.py`

Runs in the worker. Sandboxing rules: files pass the sanitizer, no shell escape flag ever, hard timeout, 20 MB PDF cap, logs always stored, temp dir removed. Failure handling rolls the session back first — committing on a session that just raised is how jobs get wedged in `running` forever.

```python
# asyncio runs the Tectonic subprocess with timeout support.
import asyncio
# shutil copies finished PDF artifacts and deletes temp dirs.
import shutil
# UTC timestamps mark compile completion.
from datetime import UTC, datetime
# Path handles workdir/artifact paths.
from pathlib import Path
# UUID identifies projects and compilation rows.
from uuid import UUID

# select loads project files.
from sqlalchemy import select
# AsyncSession is the worker DB unit of work.
from sqlalchemy.ext.asyncio import AsyncSession

# Settings supplies LATEX_WORKDIR and timeout.
from app.config import Settings
# ORM rows read/written by compiler.
from app.db.models import LatexCompilation, ProjectFile
# File paths must be project-safe before writing to disk.
from app.latex.sanitizer import sanitize_project_path
# Structured compile logs.
from app.logging import get_logger

# Module logger.
log = get_logger(__name__)

# Guardrail so a broken or malicious document cannot produce a giant artifact.
MAX_PDF_BYTES = 20 * 1024 * 1024


async def _mark_failed(
    session: AsyncSession, compilation_id: UUID, error: str, logs: str | None = None
) -> None:
    # Roll back any failed transaction state before writing failure status.
    await session.rollback()
    # Reload row in a clean transaction.
    compilation = await session.get(LatexCompilation, compilation_id)
    compilation.status = "failed"
    compilation.error = error
    if logs:
        compilation.logs = logs
    compilation.completed_at = datetime.now(UTC)
    await session.commit()
    log.warning("latex.compile.failed", compilation_id=str(compilation_id), error=error)


async def compile_project(
    session: AsyncSession,
    settings: Settings,
    project_id: UUID,
    main_file_path: str,
    compilation_id: UUID,
) -> None:
    # The API/worker created this row before enqueueing the job.
    compilation = await session.get(LatexCompilation, compilation_id)
    if compilation is None:
        raise ValueError(f"Compilation not found: {compilation_id}")

    safe_main = sanitize_project_path(main_file_path)
    # One isolated temp workdir per compilation.
    workdir = Path(settings.LATEX_WORKDIR) / str(compilation_id)
    outdir = workdir / "out"

    try:
        # Mark running before doing filesystem/subprocess work.
        compilation.status = "running"
        await session.commit()

        workdir.mkdir(parents=True, exist_ok=True)
        outdir.mkdir(parents=True, exist_ok=True)

        files = (
            (await session.execute(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )).scalars().all()
        )
        for project_file in files:
            # Sanitize every logical project path before writing it under workdir.
            target = workdir / sanitize_project_path(project_file.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(project_file.content, encoding="utf-8")

        # No shell=True and no shell-escape flag; pass args directly.
        proc = await asyncio.create_subprocess_exec(
            "tectonic", safe_main, "--outdir", str(outdir),
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            # Hard timeout prevents stuck compiles from occupying the worker forever.
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.LATEX_COMPILE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            # Kill subprocess and store failure.
            proc.kill()
            await proc.wait()
            await _mark_failed(session, compilation_id, "timeout")
            return

        # Store only the tail of logs so DB rows do not balloon.
        logs = (stdout + stderr).decode("utf-8", errors="replace")[-12000:]

        # Tectonic output PDF name matches main tex stem.
        pdf_path = outdir / Path(safe_main).with_suffix(".pdf").name
        if proc.returncode != 0 or not pdf_path.exists():
            await _mark_failed(session, compilation_id, "tectonic failed", logs=logs)
            return
        if pdf_path.stat().st_size > MAX_PDF_BYTES:
            # Size cap protects storage/UI from huge output.
            await _mark_failed(session, compilation_id, "pdf too large", logs=logs)
            return

        # Artifacts survive after temp workdir is removed.
        artifact_dir = Path(settings.LATEX_WORKDIR) / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{compilation_id}.pdf"
        shutil.copyfile(pdf_path, artifact_path)

        compilation.logs = logs
        compilation.status = "completed"
        compilation.pdf_path = str(artifact_path)
        compilation.completed_at = datetime.now(UTC)
        await session.commit()
        log.info(
            "latex.compile.completed",
            project_id=str(project_id),
            compilation_id=str(compilation_id),
        )
    except Exception as exc:
        # Any unexpected exception becomes a failed compilation row, not a stuck job.
        await _mark_failed(session, compilation_id, str(exc))
    finally:
        # Remove temp inputs/outputs after extracting artifact/logs.
        shutil.rmtree(workdir, ignore_errors=True)
```

Compiler walkthrough:

- The compiler never reads arbitrary host paths; it reconstructs project files in a temp directory.
- `asyncio.create_subprocess_exec` avoids shell interpolation entirely.
- The warm Tectonic bundle in Docker makes runtime compiles network-free.

## `infra/docker/worker.Dockerfile` (final version — replace the bootstrap one)

Tectonic downloads its package bundle over the network on first compile. Bake the cache at **build time** with a warmup document using the same preamble as the bootstrap `main.tex` — first demo compile is instant and runtime compiles need no network.

```dockerfile
# Python worker image; backend and arq run here.
FROM python:3.12-slim

# Unbuffered logs show up immediately in Docker; no pyc files keeps the image cleaner.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Backend package root.
WORKDIR /app/backend

# curl/ca-certificates are needed to install Tectonic.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Tectonic (official installer drops the binary in cwd).
RUN cd /tmp \
 && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
 && mv /tmp/tectonic /usr/local/bin/tectonic

# Pre-warm the bundle with the same preamble as the bootstrap main.tex.
RUN printf '\\documentclass{article}\\usepackage{hyperref}\\usepackage{cite}\\begin{document}warmup\\bibliographystyle{plain}\\end{document}\n' > /tmp/warmup.tex \
 && tectonic /tmp/warmup.tex --outdir /tmp \
 && rm -f /tmp/warmup.*

# Copy backend source and install editable package/dependencies.
COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

# arq imports this settings object to discover job functions.
CMD ["arq", "app.workers.arq_app.WorkerSettings"]
```

## Acceptance checks

```bash
docker compose exec backend pytest app/tests/test_latex_patcher.py app/tests/test_path_sanitizer.py
docker compose build worker && docker compose up -d worker
```

Manual (after guide 08 wires the routes): create a project → Compile → PDF appears; break `main.tex` (`\begin{documnet}`) → compile again → status `failed` with a useful log excerpt; confirm the compile worked without the worker fetching anything from the network (the warm bundle).

Interview line for this module: *"I chose a patch representation that models are good at (exact text anchors) over one they're bad at (character offsets), so failure modes became loud and retryable instead of silent corruption — plus version checks and a human approval step for UI-originated edits."*
