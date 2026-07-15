import asyncio
import contextlib
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agent.demo_orchestrator import run_demo_agent_turn
from app.agent.llm.base import LLMClient, Message
from app.config import Settings
from app.deps import get_app_settings, get_llm
from app.latex.compiler import EphemeralCompilationError, compile_ephemeral
from app.latex.sanitizer import UnsafePathError, sanitize_project_path
from app.logging import get_logger


router = APIRouter()
log = get_logger(__name__)
DEMO_FILE_SUFFIXES = {".tex", ".bib", ".sty", ".cls", ".txt"}


class DemoFile(BaseModel):
    path: str = Field(min_length=1, max_length=160)
    content: str = Field(max_length=500_000)

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        try:
            path = sanitize_project_path(value)
        except UnsafePathError as exc:
            raise ValueError(str(exc)) from exc
        if not any(path.casefold().endswith(suffix) for suffix in DEMO_FILE_SUFFIXES):
            raise ValueError("Unsupported demo file type")
        return path


class DemoCompileRequest(BaseModel):
    files: list[DemoFile] = Field(min_length=1, max_length=12)
    main_file_path: str = Field(default="main.tex", max_length=160)

    @field_validator("main_file_path")
    @classmethod
    def safe_main_file(cls, value: str) -> str:
        try:
            path = sanitize_project_path(value)
        except UnsafePathError as exc:
            raise ValueError(str(exc)) from exc
        if not path.casefold().endswith(".tex"):
            raise ValueError("Main demo file must be LaTeX")
        return path


class DemoChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class DemoPaper(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    year: int = Field(ge=1500, le=2200)
    role: str = Field(min_length=1, max_length=100)


class DemoAgentRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=120)
    files: list[DemoFile] = Field(min_length=1, max_length=12)
    papers: list[DemoPaper] = Field(default_factory=list, max_length=12)
    message: str = Field(min_length=1, max_length=2000)
    active_file_path: str | None = Field(default=None, max_length=160)
    selected_text: str | None = Field(default=None, max_length=4000)
    conversation: list[DemoChatMessage] = Field(default_factory=list, max_length=6)


def _visitor_digest(visitor_id: str) -> str:
    try:
        normalized = str(UUID(visitor_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid demo visitor token") from exc
    return hashlib.sha256(normalized.encode()).hexdigest()[:24]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _quota_keys(request: Request, visitor_id: str, action: str) -> tuple[str, str]:
    visitor = _visitor_digest(visitor_id)
    ip = hashlib.sha256(_client_ip(request).encode()).hexdigest()[:20]
    return f"demo:{action}:visitor:{visitor}", f"demo:{action}:ip:{ip}"


async def _count(redis, key: str) -> int:
    value = await redis.get(key)
    return int(value or 0)


async def _consume_quota(
    request: Request,
    visitor_id: str,
    action: Literal["agent", "preview"],
    settings: Settings,
) -> int:
    if not settings.DEMO_ENABLED:
        raise HTTPException(status_code=404, detail="Demo is disabled")
    limit = (
        settings.DEMO_AGENT_RUN_LIMIT if action == "agent" else settings.DEMO_PREVIEW_LIMIT
    )
    visitor_key, ip_key = _quota_keys(request, visitor_id, action)
    window = settings.DEMO_QUOTA_WINDOW_HOURS * 3600
    redis = request.app.state.redis

    visitor_count = await redis.incr(visitor_key)
    ip_count = await redis.incr(ip_key)
    if visitor_count == 1:
        await redis.expire(visitor_key, window)
    if ip_count == 1:
        await redis.expire(ip_key, window)
    # The wider IP ceiling prevents token rotation without punishing a normal
    # household or portfolio review behind one NAT address.
    if visitor_count > limit or ip_count > limit * 10:
        # Rejected attempts are not usage. Keep counters at their previous
        # values so repeated clicks do not extend the effective lockout.
        await asyncio.gather(redis.decr(visitor_key), redis.decr(ip_key))
        raise HTTPException(status_code=429, detail=f"Demo {action} limit reached")
    return max(0, limit - visitor_count)


async def _refund_quota(
    request: Request,
    visitor_id: str,
    action: Literal["agent", "preview"],
) -> None:
    """Return a reserved run when no usable result was produced."""
    visitor_key, ip_key = _quota_keys(request, visitor_id, action)
    await asyncio.gather(
        request.app.state.redis.decr(visitor_key),
        request.app.state.redis.decr(ip_key),
    )


def _validate_sources(files: list[DemoFile], settings: Settings) -> None:
    total = sum(len(file.content.encode("utf-8")) for file in files)
    if total > settings.DEMO_MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="Demo source files are too large")
    paths = [file.path for file in files]
    if len(paths) != len(set(paths)):
        raise HTTPException(status_code=422, detail="Demo file paths must be unique")


@router.get("/limits")
async def demo_limits(
    request: Request,
    visitor_id: Annotated[str, Header(alias="X-Demo-Visitor")],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict:
    if not settings.DEMO_ENABLED:
        raise HTTPException(status_code=404, detail="Demo is disabled")
    redis = request.app.state.redis
    agent_key, _ = _quota_keys(request, visitor_id, "agent")
    preview_key, _ = _quota_keys(request, visitor_id, "preview")
    agent_used, preview_used = await asyncio.gather(
        _count(redis, agent_key), _count(redis, preview_key)
    )
    return {
        "agent_limit": settings.DEMO_AGENT_RUN_LIMIT,
        "agent_remaining": max(0, settings.DEMO_AGENT_RUN_LIMIT - agent_used),
        "preview_limit": settings.DEMO_PREVIEW_LIMIT,
        "preview_remaining": max(0, settings.DEMO_PREVIEW_LIMIT - preview_used),
    }


@router.post("/compile")
async def demo_compile(
    body: DemoCompileRequest,
    request: Request,
    visitor_id: Annotated[str, Header(alias="X-Demo-Visitor")],
    settings: Annotated[Settings, Depends(get_app_settings)],
):
    _validate_sources(body.files, settings)
    main_path = sanitize_project_path(body.main_file_path)
    if main_path not in {file.path for file in body.files}:
        raise HTTPException(status_code=422, detail="Main LaTeX file is missing")
    remaining = await _consume_quota(request, visitor_id, "preview", settings)
    completed = False
    try:
        async with request.app.state.demo_compile_semaphore:
            result = await compile_ephemeral(
                settings,
                [(file.path, file.content) for file in body.files],
                main_path,
            )
        completed = True
    except EphemeralCompilationError as exc:
        return JSONResponse(
            {
                "detail": str(exc),
                "logs": exc.logs[-3000:],
                "remaining": remaining + 1,
            },
            status_code=422,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        if not completed:
            await _refund_quota(request, visitor_id, "preview")
    return Response(
        result.pdf,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": 'inline; filename="citepilot-demo-preview.pdf"',
            "X-Demo-Remaining": str(remaining),
        },
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/agent")
async def demo_agent(
    body: DemoAgentRequest,
    request: Request,
    visitor_id: Annotated[str, Header(alias="X-Demo-Visitor")],
    settings: Annotated[Settings, Depends(get_app_settings)],
    llm: Annotated[LLMClient, Depends(get_llm)],
):
    _validate_sources(body.files, settings)
    remaining = await _consume_quota(request, visitor_id, "agent", settings)
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def run() -> None:
        try:
            await queue.put(_sse("usage", {"agent_remaining": remaining}))
            async def emit(event: str, payload: dict) -> None:
                await queue.put(_sse(event, payload))

            await run_demo_agent_turn(
                llm=llm,
                settings=settings,
                redis=request.app.state.redis,
                project_name=body.project_name,
                files=[file.model_dump() for file in body.files],
                papers=[paper.model_dump() for paper in body.papers],
                active_file_path=body.active_file_path,
                selected_text=body.selected_text,
                conversation=[
                    Message(role=item.role, content=item.content)
                    for item in body.conversation
                ],
                user_message=body.message,
                emit=emit,
            )
            await queue.put(_sse("done", {"agent_remaining": remaining}))
        except asyncio.CancelledError:
            await _refund_quota(request, visitor_id, "agent")
            raise
        except Exception as exc:
            log.warning("demo.agent.failed", error=type(exc).__name__)
            await _refund_quota(request, visitor_id, "agent")
            await queue.put(
                _sse(
                    "error",
                    {
                        "message": "The demo agent is temporarily unavailable.",
                        "agent_remaining": remaining + 1,
                    },
                )
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())

    async def event_stream():
        try:
            while (item := await queue.get()) is not None:
                yield item
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
