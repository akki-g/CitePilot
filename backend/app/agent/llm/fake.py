# deque lets tests pop scripted responses from the left efficiently.
from collections import deque

# Fake uses the same neutral response/message/spec objects as real providers.
from app.agent.llm.base import LLMResponse, Message, ToolSpec


class FakeLLMClient:
    def __init__(self, responses: list[LLMResponse]):
        # Queue of model responses the test wants the orchestrator to see.
        self.responses = deque(responses)
        # Capture prompts/messages so tests can assert tool results were fed back.
        self.calls: list[list[Message]] = []   # inspect what the orchestrator sent

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.responses:
            # Default completion prevents tests from crashing if script runs out.
            return LLMResponse(text="Done.")
        return self.responses.popleft()