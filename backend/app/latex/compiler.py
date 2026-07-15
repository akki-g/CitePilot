# this runs in the worker
# sandboxing rules: files pass the sanitizer, no shell escape flag ever, hard timeout, 20 MB PDF cap, logs always stored, temp dir removes

import asyncio # runs tectonic subprocess w timeout support
import shutil # copies finished PDF artifacts and deletes temp dir
import tempfile
from dataclasses import dataclass

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import LatexCompilation, ProjectFile
from app.latex.sanitizer import sanitize_project_path

from app.logging import get_logger

log = get_logger(__name__)


MAX_PDF_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class EphemeralCompilation:
    pdf: bytes
    logs: str


class EphemeralCompilationError(Exception):
    def __init__(self, message: str, logs: str = ""):
        super().__init__(message)
        self.logs = logs


async def compile_ephemeral(
    settings: Settings,
    files: list[tuple[str, str]],
    main_file_path: str = "main.tex",
) -> EphemeralCompilation:
    """Compile caller-supplied files without touching Postgres or durable artifacts."""
    safe_main = sanitize_project_path(main_file_path)
    base = Path(settings.LATEX_WORKDIR)
    base.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="demo-", dir=base) as temp:
        workdir = Path(temp)
        outdir = workdir / "out"
        outdir.mkdir()
        for logical_path, content in files:
            target = workdir / sanitize_project_path(logical_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            "tectonic",
            safe_main,
            "--outdir",
            str(outdir),
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.LATEX_COMPILE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise EphemeralCompilationError("Preview compilation timed out") from exc

        logs = (stdout + stderr).decode("utf-8", errors="replace")[-8000:]
        pdf_path = outdir / Path(safe_main).with_suffix(".pdf").name
        if proc.returncode != 0 or not pdf_path.exists():
            raise EphemeralCompilationError("LaTeX compilation failed", logs)
        if pdf_path.stat().st_size > 5 * 1024 * 1024:
            raise EphemeralCompilationError("Demo preview is too large", logs)
        return EphemeralCompilation(pdf=pdf_path.read_bytes(), logs=logs)

async def _mark_failed(
        session: AsyncSession, compilation_id: UUID, error: str, logs: str | None = None
) -> None:
    # rollback any failed transaction state before writing failure status
    await session.rollback()
    # reload row in a clean transaction 
    compilation = await session.get(LatexCompilation, compilation_id)
    compilation.status = "failed"
    compilation.error = error

    if logs:
        compilation.logs = logs

    compilation.completed_at = datetime.now(UTC)
    await session.commit()
    log.warning("latex.compilation.failed", compilation_id=str(compilation_id), error=error)


async def compile_project(
        session: AsyncSession,
        settings: Settings,
        project_id: UUID,
        main_file_path: str,
        compilation_id: UUID,
) -> None:
    # the api/worker created this row before enqueuing the job
    compilation = await session.get(LatexCompilation, compilation_id)
    if compilation is None:
        raise ValueError(f"Compilation not found at: {compilation_id}")
    
    safe_main = sanitize_project_path(main_file_path)
    # one isolated temp workdir per compilation
    workdir = Path(settings.LATEX_WORKDIR) / str(compilation_id)
    outdir = workdir / "out"

    try:
        # mark running before doing filesystem/subprocess work
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
            # sanitize every logical project path before writing it under work dir
            target = workdir / sanitize_project_path(project_file.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(project_file.content, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            "tectonic", safe_main, "--outdir", str(outdir),
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            # hard timeout prevent stuck compiles from occupying the worker forever
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.LATEX_COMPILE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            # kill subprocess and store failure
            proc.kill()
            await proc.wait()
            await _mark_failed(session, compilation_id, "timeout")
            return
        
        # store only tail of logs so rows dont ballon
        logs = (stdout + stderr).decode("utf-8", errors="replace")[-12000:]

        # tectonic output pdf name matches main tex stem
        pdf_path = outdir / Path(safe_main).with_suffix(".pdf").name
        if proc.returncode != 0 or not pdf_path.exists():
            await _mark_failed(session, compilation_id, "tectonic failed", logs=logs)
            return
        
        if pdf_path.stat().st_size > MAX_PDF_BYTES:
            await _mark_failed(session, compilation_id, "pdf too large", logs=logs)
            return
        
        # artifacts survive after temp workdir is removed
        artifact_dir = Path(settings.LATEX_WORKDIR) / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{compilation_id}.pdf"
        shutil.copyfile(pdf_path, artifact_path)

        compilation.logs = logs
        # fix: status was "compiled" — the rest of the system (routes, UI polling) expects "completed"
        compilation.status = "completed"
        compilation.pdf_path = str(artifact_path)
        compilation.completed_at = datetime.now(UTC)

        await session.commit()

        log.info(
            "latex.compilation.completed",
            project_id=str(project_id),
            compilation_id=str(compilation_id),
        )
    
    except Exception as exc:
        await _mark_failed(session, compilation_id, str(exc))
    
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
