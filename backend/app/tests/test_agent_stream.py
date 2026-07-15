from pydantic import BaseModel
from sqlalchemy import select

from app.agent.llm.base import LLMResponse, ToolCall
from app.agent.llm.fake import FakeLLMClient
from app.agent.orchestrator import AgentTurnContext, run_agent_turn
from app.agent.schemas import ToolError
from app.db.models import AgentMessage, AgentSession, ToolCallRecord


class EchoOutput(BaseModel):
    ok: bool = True
    summary: str = "echo done"


class FakeRegistry:
    def specs(self):
        return []

    def is_project_scoped(self, name):
        # mirror the real registry: project tools get project_id pinned by the
        # orchestrator, so the fake opts in to exercise that path
        return True

    async def execute(self, name, arguments):
        return EchoOutput(summary=f"{name} executed")


class FailingRegistry(FakeRegistry):
    async def execute(self, name, arguments):
        raise ToolError("anchor_ambiguous", "anchor occurs 3 times; use a longer anchor")


async def _agent_session(db_session, project) -> AgentSession:
    session_row = AgentSession(project_id=project.id, user_id=project.user_id, title="test")
    db_session.add(session_row)
    await db_session.commit()
    return session_row


async def test_agent_stream_event_sequence(db_session, project):
    agent_session = await _agent_session(db_session, project)
    llm = FakeLLMClient(
        [
            LLMResponse(
                text="Inspecting the project.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="inspect_latex_project",
                        arguments={"project_id": str(project.id)},
                    )
                ],
            ),
            LLMResponse(text="Here are my suggestions."),
        ]
    )
    events: list[tuple[str, dict]] = []

    async def emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    turn = AgentTurnContext(project_id=project.id, project_name=project.name)
    await run_agent_turn(
        db_session, agent_session.id, "suggest citations", turn, FakeRegistry(), llm, emit
    )

    assert [n for n, _ in events] == [
        "message_delta", "tool_call", "tool_result", "message_delta", "done",
    ]

    records = (
        await db_session.execute(
            select(ToolCallRecord).where(ToolCallRecord.session_id == agent_session.id)
        )
    ).scalars().all()
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].tool_name == "inspect_latex_project"

    roles = [
        m.role
        for m in (
            await db_session.execute(
                select(AgentMessage)
                .where(AgentMessage.session_id == agent_session.id)
                .order_by(AgentMessage.created_at)
            )
        ).scalars()
    ]
    assert roles == ["user", "assistant"]


async def test_tool_error_flows_back_into_conversation(db_session, project):
    agent_session = await _agent_session(db_session, project)
    llm = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall(id="c1", name="inspect_latex_project", arguments={})],
            ),
            LLMResponse(text="I hit an error and adjusted."),
        ]
    )
    events: list[tuple[str, dict]] = []

    async def emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    turn = AgentTurnContext(project_id=project.id, project_name=project.name)
    await run_agent_turn(
        db_session, agent_session.id, "edit the intro", turn, FailingRegistry(), llm, emit
    )

    tool_results = [p for n, p in events if n == "tool_result"]
    assert tool_results[0]["error"] == "anchor_ambiguous"

    # the model sent empty arguments; the orchestrator must have pinned the
    # turn's project_id before recording/executing the call
    records = (
        await db_session.execute(
            select(ToolCallRecord).where(ToolCallRecord.session_id == agent_session.id)
        )
    ).scalars().all()
    assert records[0].arguments["project_id"] == str(project.id)

    # errors are data: the SECOND llm call must contain the error as a tool message
    second_call_messages = llm.calls[1]
    tool_messages = [m for m in second_call_messages if m.role == "tool"]
    assert tool_messages and "anchor_ambiguous" in tool_messages[0].content
