import asyncio
import contextlib
import json
from datetime import UTC, datetime
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm.base import LLMClient
from app.agent.orchestrator import AgentTurnContext, run_agent_turn
from app.agent.schemas import PatchLatexFileInput, ToolError
from app.agent.tool_registry import build_default_registry
from app.agent.tools import ToolContext, patch_latex_file
from app.api.routes.projects import ensure_dev_user
from app.config import Settings
from app.db.models import AgentMessage, AgentSession, Project, ToolCallRecord
from app.deps import get_app_settings, get_arq_pool, get_db, get_llm, get_neo4j, get_redis
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


class AgentStreamRequest(BaseModel):
    project_id: UUID
    session_id: UUID | None = None
    message: str
    active_file_path: str | None = None
    selected_text: str | None = None


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: UUID, session: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await session.execute(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at)
        )
    ).scalars().all()
    return [
        {"id": str(m.id), "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in rows
    ]


@router.post("/stream")
async def stream_agent(
    body: AgentStreamRequest,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    llm: LLMClient = Depends(get_llm),
):
    project = await session.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if body.session_id:
        agent_session = await session.get(AgentSession, body.session_id)
        if agent_session is None or agent_session.project_id != project.id:
            raise HTTPException(status_code=404, detail="agent session not found")
    else:
        user = await ensure_dev_user(session, settings)
        agent_session = AgentSession(
            project_id=project.id, user_id=user.id, title=body.message[:80]
        )
        session.add(agent_session)
        await session.commit()

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event_name: str, payload: dict) -> None:
        await queue.put(sse(event_name, payload))

    async def run() -> None:
        # fix: create_llm_client used to run before the try block — a config error
        # (e.g. missing LLM_API_KEY) killed the task before any event or the
        # None sentinel reached the queue, so the SSE response hung forever
        try:
            # ack immediately so the client knows the stream is alive and can
            # bind the session id before the first (slow) LLM call returns
            await emit("session", {"session_id": str(agent_session.id)})
            ctx = ToolContext(session, settings, neo4j, redis, arq_pool)
            registry = build_default_registry(ctx)
            turn = AgentTurnContext(
                project_id=project.id,
                project_name=project.name,
                active_file_path=body.active_file_path,
                selected_text=body.selected_text,
                auto_apply_patches=False,
            )
            await run_agent_turn(
                session, agent_session.id, body.message, turn, registry, llm, emit
            )
        except Exception as exc:
            log.error("agent.stream.failed", session_id=str(agent_session.id), error=str(exc))
            await queue.put(sse("error", {"message": str(exc)}))
        finally:
            await queue.put(None)   # sentinel: stream is over

    task = asyncio.create_task(run())

    async def event_stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:                     # client disconnected or stream finished
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/patches/{tool_call_id}/accept")
async def accept_patch(
    tool_call_id: UUID,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    neo4j=Depends(get_neo4j),
    redis=Depends(get_redis),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    record = await session.get(ToolCallRecord, tool_call_id)
    if record is None or record.tool_name != "patch_latex_file":
        raise HTTPException(status_code=404, detail="patch proposal not found")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail=f"patch already {record.status}")

    ctx = ToolContext(session, settings, neo4j, redis, arq_pool)
    try:
        args = PatchLatexFileInput.model_validate(record.arguments)
        output = await patch_latex_file(ctx, args)
    except ToolError as exc:
        record.status = "failed"
        record.error = f"{exc.code}: {exc.message}"
        record.completed_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(status_code=422, detail=exc.as_tool_result())

    payload = output.model_dump(mode="json")
    record.status = "completed"
    record.result = payload
    record.completed_at = datetime.now(UTC)
    await session.commit()
    return payload
