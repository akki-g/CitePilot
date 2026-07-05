# raw httpx against the messages api, so no sdk dependency
# system messages -> top-level system string; assistant tool calls -> tool use content blocks; tool messages 
# -> tool results blocks inside a user message (constructive tool results merge into one user message, as the API requires)

from typing import Any
import httpx
from app.agent.llm.base import LLMResponse, Message, ToolCall, ToolSpec

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required for the anthropic client")
        
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self):
        await self.client.aclose()

    async def complete(
            self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        # convert neutral messages into anthropic wire format
        system, wire_messages = self._to_wire(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": wire_messages,
        }

        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]

        resp = await self.client.post(
            API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json=payload
        )

        resp.raise_for_status()
        data = resp.json()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        # anthropic response content is a list of text/tool_use blocks
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append(
                    ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {})
                )
        
        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls)
    

    @staticmethod
    def _to_wire(messages: list[Message]) -> tuple[str, list[dict]]:
        # anthropic separates system prompt from normal messages
        system_parts: list[str] = []
        wire: list[dict] = []

        for message in messages:
            if message.role == "system":
                system_parts.append(message.content)
            elif message.role == "assistant":
                blocks: list[dict] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                    )
                if blocks:
                    wire.append({"role": "assistant", "content": blocks})
            elif message.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})
            else:
                wire.append({"role": "user", "content": message.content})
        return "\n\n".join(system_parts), wire
