from app.agent.demo_orchestrator import _execute_tool
from app.config import Settings


async def test_demo_agent_tools_inspect_and_propose_in_memory_patch():
    files = [{"path": "main.tex", "content": "Hello draft"}]
    events: list[tuple[str, dict]] = []

    async def emit(event: str, payload: dict) -> None:
        events.append((event, payload))

    inspected = await _execute_tool(
        "inspect_latex_project",
        {"paths": ["main.tex"]},
        files=files,
        papers=[],
        settings=Settings(),
        redis=None,
        emit=emit,
    )
    proposal = await _execute_tool(
        "patch_latex_file",
        {
            "patch": {
                "operation": "replace_text",
                "path": "main.tex",
                "base_version": 1,
                "old_text": "Hello",
                "new_text": "Improved",
            }
        },
        files=files,
        papers=[],
        settings=Settings(),
        redis=None,
        emit=emit,
    )

    assert inspected["files"][0]["content"] == "Hello draft"
    assert proposal["status"] == "proposed"
    assert files[0]["content"] == "Hello draft"
    assert events[0][0] == "patch_proposal"
    assert events[0][1]["preview"]["after"] == "Improved draft"
