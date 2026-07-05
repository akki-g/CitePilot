# the bounded tool loop. 
from __future__ import annotations

import json 
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm.base import LLMClient, Message
from app.agent.prompts import SYSTEM_PROMPT, build_user_context
from app.agent.schemas import ToolError
from app.agent.tool_registry import ToolRegistry
from app.db.models import AgentMessage, AgentSession, ToolCallRecord
from app.latex.patcher import PatchError, preview_patch, PATCH_ADAPTER
from app.logging import get_logger

log = get_logger(__name__)

# hard loop bound: agents must not run forever
MAX_TOOL_ITERATIONS = 8

# tool call results can be very large, so db storage is capped
RESULT_TRUNCATE_BYTES = 4096

# emit(event_name, payload) pushes an SSE event to the client
EmitFn = Callable[[str, dict], Awaitable[None]]

@dataclass
class AgentTurnContext:
    # request specific context passed to the orchestrator
    project_id: UUID
    project_name: str = ""
    active_file_path: str | None = None
    selected_text: str | None = None
    auto_apply_patches: bool = False # false in the web ui; true over mcp

def truncate_result(payload: dict, limit: int = RESULT_TRUNCATE_BYTES) -> dict:
    # Store full small results, previews for large results.
    encoded = json.dumps(payload, default=str)
    if len(encoded) <= limit:
        return payload
    return {"truncated": True, "preview": encoded[:limit]}

async def _load_history(db: AsyncSession, session_id: UUID) -> list[Message]:
    # Reload prior user/assistant messages for continuity.
    rows = (
        await db.execute(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at)
        )
    ).scalars().all()
    return [Message(role=r.role, content=r.content) for r in rows if r.role in ("user", "assistant")]


async def run_agent_turn(
    db: AsyncSession,
    agent_session_id: UUID,
    user_message: str,
    turn: AgentTurnContext,
    registry: ToolRegistry,
    llm: LLMClient,
    emit: EmitFn,
) -> None:
    # build initial message list: system prompt, history, current contextual user message
    history = await _load_history(db, agent_session_id)

    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        *history,
        Message(
            role="user",
            content=build_user_context(
                turn.project_name, turn.active_file_path, turn.selected_text, user_message
            ),
        ),
    ]
    db.add(AgentMessage(session_id=agent_session_id, role="user", content=user_message))
    await db.commit

    final_text = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        response = await llm.complete(messages, tools=registry.specs())

        if response.text:
            # stream text to ui as message_delta event
            final_text = response.text
            await emit("message_delta", {"text": response.text})

        messages.append(
            Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )

        if not response.tool_calls:
            # no tool calls means the turn is complete
            break

        for call in response.tool_calls:
            await emit("tool_call", {"tool_name": call.name, "arguments":call.arguments})
            record = ToolCallRecord(
                session_id=agent_session_id, tool_name=call.name, arguments=call.arguments
            )

            db.add(record)
            await db.commit()

            if call.name == "patch_latex_file" and not turn.auto_apply_patches:
                # web ui path: propose patch for human approval
                payload = await _propose_patch(db, turn, call, record, emit)
            else:
                payload = await _execute_call(db, registry, call, record, emit)

            messages.append(
                Message(role="tool", content=json.dumps(payload, default=str), tool_call_id=call.id)
            )

    db.add(AgentMessage(session_id=agent_session_id, role="assistant", content=final_text))
    session_row = await db.get(AgentSession, agent_session_id)
    if session_row is not None:
        session_row.updated_at = datetime.now(UTC)
    await db.commit()
    await emit("done", {"session_id": str(agent_session_id)})

async def _finish_record(
    db: AsyncSession, record: ToolCallRecord, status: str, result: dict | None, error: str | None
) -> None:
    record.status = status
    record.result = result
    record.error = error
    record.completed_at = datetime.now(UTC)
    await db.commit()

async def _execute_call(
        db: AsyncSession, registry: ToolRegistry, call, record:ToolCallRecord, emit: EmitFn
) -> dict:
    try:
        # registry validates args and calls the core tool
        output = await registry.execute(call.name, call.arguments)  
    except ToolError as exc:
        await _finish_record(db, record, "failed", None, f"{exc.code}: {exc.message}")
        await _finish_record(db, record, "failed", None, f"{exc.code}: {exc.message}")
        await emit("tool_result", {"tool_name": call.name, "error": exc.code, "message": exc.message})
        log.warning("agent.tool.failed", tool=call.name, code=exc.code)
        return exc.as_tool_result()
    
    payload = output.model_dump(mode="json")
    await _finish_record(db, record, "completed", truncate_result(payload), None)
    await emit("tool_result", {"tool_name": call.name, "summary": payload.get("summary") or "ok"})
    log.info("agent.tool.completed", tool=call.name)

    if call.name == "rank_related_work":
        # special event lets ui render citation cards directly
        await emit("citation_suggestions", {"recommendations": payload.get("recommendations", [])})

    return payload


async def _propose_patch(
        db: AsyncSession, turn: AgentTurnContext, call, record: ToolCallRecord, emit: EmitFn
) -> dict:
    """
    web ui flow: preview instead of apply. the pending tool_calls row is the 
    handle the accept endpoint uses to apply the patch after user approval
    """
    try:
        # validate and preview patch without mutating files
        patch = PATCH_ADAPTER.validate_python(call.arguments.get("patch") or {})
        preview = await preview_patch(db, turn.project_id, patch)
    except (PatchError, ValidationError) as exc:
        code = exc.code if isinstance(exc, PatchError) else "invalid_arguments"
        message = exc.message if isinstance(exc, PatchError) else str(exc)
        await _finish_record(db, record, "failed", None, f"{code}: {message}")
        await emit("tool_result", {"tool_name": call.name, "error": code, "message": message})
        return {"ok": False, "error": code, "message": message}
    
    record.result = {"proposed": True}   # status stays 'pending' until accepted
    await db.commit()
    await emit(
        "patch_proposal",
        {"tool_call_id": str(record.id), "patch": call.arguments.get("patch"), "preview": preview},
    )
    await emit(
        "tool_result",
        {"tool_name": call.name, "summary": "patch proposed; awaiting user approval"},
    )
    return {
        "status": "proposed",
        "tool_call_id": str(record.id),
        "summary": "Patch proposed to the user for approval. Do not retry unless they reject it.",
    }