from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass(frozen=True)
class ToolSpec:
    # tool name shown to the model
    name: str
    description: str
    input_schema: dict[str, Any]

@dataclass(frozen=True)
class ToolCall:
    # provider generated call id; tool results must point back to it
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class Message:
    """role: 'system' | 'user' | 'assistant' | 'tool' """

    role: str
    # fix: content field was missing — every Message(role=..., content=...) construction
    # across the orchestrator and adapters raised TypeError without it
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


# called with each text chunk as the provider streams it
OnTextDelta = Callable[[str], Awaitable[None]]


# standard interface for different providers
class LLMClient(Protocol):
    async def complete(
            self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse: ...


# providers that can stream tokens implement this superset; the orchestrator
# probes for `stream` with getattr and falls back to complete() otherwise
class StreamingLLMClient(LLMClient, Protocol):
    async def stream(
            self,
            messages: list[Message],
            tools: list[ToolSpec] | None = None,
            on_text: OnTextDelta | None = None,
    ) -> LLMResponse: ...