# raw httpx against the messages api, so no sdk dependency
# system messages -> top-level system blocks; assistant tool calls -> tool use content blocks; tool messages
# -> tool results blocks inside a user message (constructive tool results merge into one user message, as the API requires)
#
# complete() buffers a whole response; stream() uses the SSE streaming API and
# invokes on_text with each text delta so the UI renders tokens as they arrive.
# cache_control markers on the tool list and system prompt enable Anthropic
# prompt caching, which cuts time-to-first-token on every turn after the first.

import json
from typing import Any

import httpx

from app.agent.llm.base import LLMResponse, Message, OnTextDelta, ToolCall, ToolSpec

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# streaming holds the connection open while the model thinks between chunks;
# read applies per-chunk, so it only needs to cover inter-chunk gaps
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required for the anthropic client")

        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=TIMEOUT)

    async def aclose(self):
        await self.client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def _payload(
            self, messages: list[Message], tools: list[ToolSpec] | None
    ) -> dict[str, Any]:
        system, wire_messages = self._to_wire(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": wire_messages,
        }

        if system:
            # system as a block list so the last block can carry a cache marker
            payload["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if tools:
            wire_tools = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
            # caching the tool list caches everything up to and including it
            wire_tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = wire_tools
        return payload

    async def complete(
            self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        return await self.stream(messages, tools, on_text=None)

    async def stream(
            self,
            messages: list[Message],
            tools: list[ToolSpec] | None = None,
            on_text: OnTextDelta | None = None,
    ) -> LLMResponse:
        payload = self._payload(messages, tools)
        payload["stream"] = True

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        # tool_use inputs arrive as partial json fragments keyed by block index
        open_blocks: dict[int, dict[str, Any]] = {}

        async with self.client.stream(
            "POST", API_URL, headers=self._headers(), json=payload
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode(errors="replace")
                raise httpx.HTTPStatusError(
                    f"anthropic api returned {resp.status_code}: {body[:500]}",
                    request=resp.request,
                    response=resp,
                )

            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue

                kind = event.get("type")
                if kind == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        open_blocks[event["index"]] = {
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "json": "",
                        }
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text") or ""
                        if chunk:
                            text_parts.append(chunk)
                            if on_text is not None:
                                await on_text(chunk)
                    elif delta.get("type") == "input_json_delta":
                        pending = open_blocks.get(event["index"])
                        if pending is not None:
                            pending["json"] += delta.get("partial_json") or ""
                elif kind == "content_block_stop":
                    pending = open_blocks.pop(event["index"], None)
                    if pending is not None:
                        try:
                            arguments = json.loads(pending["json"]) if pending["json"] else {}
                        except json.JSONDecodeError:
                            arguments = {}
                        tool_calls.append(
                            ToolCall(id=pending["id"], name=pending["name"], arguments=arguments)
                        )
                elif kind == "error":
                    detail = (event.get("error") or {}).get("message", "unknown stream error")
                    raise RuntimeError(f"anthropic stream error: {detail}")

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
