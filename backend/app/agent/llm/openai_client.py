import json
# Any for provider payload dictionaries.
from typing import Any

# Direct HTTP client.
import httpx

from app.agent.llm.base import LLMResponse, Message, ToolCall, ToolSpec

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIClient:
    def __init__(self, api_key: str, model: str):
        # Fail fast if real provider is selected but not configured.
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required for the OpenAI client")
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=120)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        # OpenAI chat completions payload.
        payload: dict[str, Any] = {"model": self.model, "messages": self._to_wire(messages)}
        if tools:
            # OpenAI tools are wrapped as function tool objects.
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]

        resp = await self.client.post(
            API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]

        tool_calls = [
            # function.arguments is JSON text, not a dict.
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"] or "{}"),
            )
            for tc in message.get("tool_calls") or []
        ]
        return LLMResponse(text=message.get("content") or "", tool_calls=tool_calls)

    @staticmethod
    def _to_wire(messages: list[Message]) -> list[dict]:
        # Convert neutral Message objects to OpenAI chat messages.
        wire: list[dict] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                wire.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                            }
                            for c in m.tool_calls
                        ],
                    }
                )
            elif m.role == "tool":
                wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            else:
                wire.append({"role": m.role, "content": m.content})
        return wire