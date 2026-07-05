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
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


# standard interface for different providers
class LLMClient(Protocol):
    async def complete(
            self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse: ...