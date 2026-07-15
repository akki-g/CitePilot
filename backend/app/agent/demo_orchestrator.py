"""Bounded, stateless version of the CitePilot tool loop for the public demo."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.llm.base import LLMClient, Message, ToolSpec
from app.agent.prompts import SYSTEM_PROMPT, build_user_context
from app.config import Settings
from app.ingestion.normalize import normalize_openalex_work
from app.ingestion.openalex import OpenAlexClient
from app.latex.patcher import PATCH_ADAPTER, PatchError, preview_patch_content


EmitFn = Callable[[str, dict], Awaitable[None]]
MAX_DEMO_TOOL_ITERATIONS = 4


class InspectInput(BaseModel):
    project_id: str | None = None
    paths: list[str] | None = None


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    source: Literal["local", "openalex"] = "local"
    project_id: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    limit: int = Field(default=5, ge=1, le=8)


class EvidenceInput(BaseModel):
    project_id: str | None = None
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=8)


class RankInput(BaseModel):
    project_id: str | None = None
    section_text: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=8)


class NeighborhoodInput(BaseModel):
    paper_id: str | None = None
    bibtex_key: str | None = None
    per_hop: int = Field(default=5, ge=1, le=10)


class PatchInput(BaseModel):
    project_id: str | None = None
    patch: dict[str, Any]


TOOL_MODELS: dict[str, type[BaseModel]] = {
    "inspect_latex_project": InspectInput,
    "search_papers": SearchInput,
    "retrieve_evidence": EvidenceInput,
    "rank_related_work": RankInput,
    "get_citation_neighborhood": NeighborhoodInput,
    "patch_latex_file": PatchInput,
}


TOOL_DESCRIPTIONS = {
    "inspect_latex_project": (
        "Read the current ephemeral LaTeX files. Use this before making claims about "
        "the draft or proposing an edit. File versions are always 1 in demo mode."
    ),
    "search_papers": (
        "Search scholarly papers. source='local' searches the demo project's evidence; "
        "source='openalex' performs a live, read-only OpenAlex search when configured."
    ),
    "retrieve_evidence": (
        "Retrieve grounded evidence from the papers connected to this demo project."
    ),
    "rank_related_work": (
        "Recommend project citations for a passage and return real bibliography keys."
    ),
    "get_citation_neighborhood": (
        "Inspect the visible demo citation neighborhood and the role of each source."
    ),
    "patch_latex_file": (
        "Propose a reviewable, exact-anchor LaTeX edit. Use base_version=1 and either "
        "replace_text or insert_after. The user must approve it in the browser."
    ),
}


def _tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name=name,
            description=TOOL_DESCRIPTIONS[name],
            input_schema=model.model_json_schema(),
        )
        for name, model in TOOL_MODELS.items()
    ]


def _paper_payload(paper: dict[str, Any], *, score: float = 1.0) -> dict[str, Any]:
    return {
        "paper_id": paper.get("key"),
        "bibtex_key": paper.get("key"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "role": paper.get("role"),
        "score": score,
        "reason": f"Connected as a {paper.get('role', 'related')} source in the demo graph.",
        "evidence_snippets": [
            f"{paper.get('title')} is a {paper.get('role', 'related')} source in this project."
        ],
        "imported": True,
        "is_stub": False,
    }


def _rank_papers(papers: list[dict[str, Any]], text: str, limit: int) -> list[dict[str, Any]]:
    terms = {word.strip(".,:;!?()[]{}").casefold() for word in text.split() if len(word) > 3}
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, paper in enumerate(papers):
        haystack = f"{paper.get('title', '')} {paper.get('role', '')}".casefold()
        overlap = sum(term in haystack for term in terms)
        ranked.append((1.0 + overlap - index * 0.01, paper))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [_paper_payload(paper, score=score) for score, paper in ranked[:limit]]


async def _execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    files: list[dict[str, str]],
    papers: list[dict[str, Any]],
    settings: Settings,
    redis,
    emit: EmitFn,
) -> dict[str, Any]:
    model = TOOL_MODELS.get(name)
    if model is None:
        return {"ok": False, "error": "unknown_tool", "message": f"Unknown tool: {name}"}
    try:
        parsed = model.model_validate(arguments)
    except ValidationError as exc:
        return {
            "ok": False,
            "error": "invalid_arguments",
            "message": str(exc.errors()[:3]),
        }

    if isinstance(parsed, InspectInput):
        requested = set(parsed.paths or [])
        selected = [file for file in files if not requested or file["path"] in requested]
        return {
            "files": [{**file, "version": 1} for file in selected],
            "summary": f"inspected {len(selected)} ephemeral files",
        }

    if isinstance(parsed, SearchInput):
        if parsed.source == "local":
            matches = _rank_papers(papers, parsed.query, parsed.limit)
            return {"papers": matches, "summary": f"found {len(matches)} project papers"}
        if not settings.OPENALEX_MAILTO:
            return {
                "ok": False,
                "error": "provider_unavailable",
                "message": "Live OpenAlex search is not configured; use source='local'.",
            }
        client = OpenAlexClient(settings, redis)
        try:
            data = await client.search_works(parsed.query, limit=parsed.limit)
        finally:
            await client.aclose()
        results = []
        for work in data.get("results", []):
            normalized = normalize_openalex_work(work)
            if parsed.year_min and normalized.publication_year and normalized.publication_year < parsed.year_min:
                continue
            if parsed.year_max and normalized.publication_year and normalized.publication_year > parsed.year_max:
                continue
            results.append(
                {
                    "external_id": normalized.source_id,
                    "title": normalized.title,
                    "year": normalized.publication_year,
                    "authors": [author.name for author in normalized.authors[:5]],
                    "abstract": (normalized.abstract or "")[:700] or None,
                    "cited_by_count": normalized.cited_by_count or 0,
                    "imported": False,
                }
            )
        return {"papers": results, "summary": f"found {len(results)} OpenAlex papers"}

    if isinstance(parsed, (EvidenceInput, RankInput)):
        text = parsed.query if isinstance(parsed, EvidenceInput) else parsed.section_text
        ranked = _rank_papers(papers, text, parsed.limit)
        key = "evidence" if isinstance(parsed, EvidenceInput) else "recommendations"
        return {key: ranked, "summary": f"ranked {len(ranked)} grounded project sources"}

    if isinstance(parsed, NeighborhoodInput):
        return {
            "nodes": [_paper_payload(paper) for paper in papers],
            "edges": [
                {"source": papers[index]["key"], "target": papers[index + 1]["key"], "type": "RELATED"}
                for index in range(max(0, len(papers) - 1))
            ],
            "summary": "loaded the ephemeral project's visible citation neighborhood",
        }

    if isinstance(parsed, PatchInput):
        try:
            patch = PATCH_ADAPTER.validate_python(parsed.patch)
            file = next((item for item in files if item["path"] == patch.path), None)
            if file is None:
                raise PatchError("file_not_found", f"No demo file at {patch.path}")
            after = preview_patch_content(file["content"], patch)
        except (PatchError, ValidationError, StopIteration) as exc:
            return {"ok": False, "error": "invalid_patch", "message": str(exc)}
        preview = {"path": patch.path, "before": file["content"], "after": after}
        await emit("patch_proposal", {"patch": parsed.patch, "preview": preview})
        return {
            "status": "proposed",
            "summary": "Patch proposed for browser approval; do not claim it is applied.",
        }

    return {"ok": False, "error": "unavailable", "message": "Tool unavailable"}


async def run_demo_agent_turn(
    *,
    llm: LLMClient,
    settings: Settings,
    redis,
    project_name: str,
    files: list[dict[str, str]],
    papers: list[dict[str, Any]],
    active_file_path: str | None,
    selected_text: str | None,
    conversation: list[Message],
    user_message: str,
    emit: EmitFn,
) -> None:
    demo_rules = """

Demo boundary:
- This is an ephemeral project, but you have the same bounded tool-calling behavior as CitePilot.
- Inspect files and use retrieval tools before making project-specific or citation claims.
- Live searches are read-only. Nothing can be imported or persisted.
- LaTeX edits are proposals that require explicit browser approval.
"""
    messages = [
        Message(role="system", content=SYSTEM_PROMPT + demo_rules),
        *conversation,
        Message(
            role="user",
            content=build_user_context(
                "ephemeral-demo",
                project_name,
                active_file_path,
                selected_text,
                user_message,
            ),
        ),
    ]
    specs = _tool_specs()
    stream = getattr(llm, "stream", None)

    async def on_text(chunk: str) -> None:
        await emit("message_delta", {"text": chunk})

    for _ in range(MAX_DEMO_TOOL_ITERATIONS):
        if stream is not None:
            response = await stream(messages, tools=specs, on_text=on_text)
        else:
            response = await llm.complete(messages, tools=specs)
            if response.text:
                await on_text(response.text)
        messages.append(
            Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )
        if not response.tool_calls:
            return
        for call in response.tool_calls:
            await emit("tool_call", {"tool_name": call.name, "arguments": call.arguments})
            result = await _execute_tool(
                call.name,
                call.arguments,
                files=files,
                papers=papers,
                settings=settings,
                redis=redis,
                emit=emit,
            )
            await emit(
                "tool_result",
                {
                    "tool_name": call.name,
                    "summary": result.get("summary") or result.get("message") or "completed",
                    "ok": result.get("ok", True),
                },
            )
            messages.append(
                Message(role="tool", content=json.dumps(result, default=str), tool_call_id=call.id)
            )

    await emit(
        "message_delta",
        {"text": "\n\nI reached the demo tool-step limit. Narrow the request and try another turn."},
    )
