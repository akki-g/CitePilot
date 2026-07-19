# Module Guide: Agent and LLM

Files in this guide (all complete — type them as-is):

- `backend/app/agent/schemas.py`
- `backend/app/agent/prompts.py`
- `backend/app/agent/llm/base.py`
- `backend/app/agent/llm/fake.py`
- `backend/app/agent/llm/anthropic_client.py`
- `backend/app/agent/llm/openai_client.py`
- `backend/app/agent/llm/providers.py`
- `backend/app/agent/tools.py` ⭐ core learning file
- `backend/app/agent/tool_registry.py` ⭐ core learning file
- `backend/app/agent/orchestrator.py` ⭐ core learning file

**Why this module:** every production agent, stripped of branding, is this: a **bounded loop** that calls an LLM with typed tool specs, executes requested tools, and feeds results (including errors — errors are data) back into the conversation. No hidden intent classifier — tool selection *is* intent classification; a router would add latency and a new failure mode for zero capability.

Two deliberate architecture decisions made here:

1. **Non-streaming LLM calls.** Each loop iteration emits its full text as one `message_delta`. The SSE event protocol already supports token-level deltas, so upgrading later is a client change in one place. This cuts the LLM adapters to ~80 lines each.
2. **Web patches are proposals.** In the web UI, `patch_latex_file` is intercepted: the agent's patch is previewed to the user (`patch_proposal` event) and applied only via the accept endpoint (guide 08). Over MCP there's no UI, so patches apply directly — versioning is the safety net.

**Comment style:** schemas are kept readable, so explanations focus on the purpose of each input/output model. The core loop and registry get extra comments because they are the main learning surface.

---

## `backend/app/agent/schemas.py`

Pydantic I/O for all ten tools + the structured `ToolError`. Every output model has a `summary` — it becomes the tool-trace line in the UI.

```python
# Any is used for arbitrary JSON-like error details.
from typing import Any, Literal
# UUID gives typed IDs in tool inputs/outputs.
from uuid import UUID

# BaseModel validates tool JSON; Field adds defaults and bounds.
from pydantic import BaseModel, Field


class ToolError(Exception):
    """Structured tool failure. Flows back into the agent conversation so the
    model can correct itself and retry."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        # Exception text is model/user-readable.
        super().__init__(message)
        # Stable machine-readable code like "not_found" or "invalid_arguments".
        self.code = code
        self.message = message
        self.details = details or {}

    def as_tool_result(self) -> dict[str, Any]:
        # Tool errors become data passed back to the LLM so it can self-correct.
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


class SearchPapersInput(BaseModel):
    query: str
    source: Literal["local", "openalex"] = "openalex"
    year_min: int | None = None
    year_max: int | None = None
    limit: int = Field(default=10, ge=1, le=50)


class PaperSearchResult(BaseModel):
    paper_id: UUID | None = None
    external_id: str | None = None
    title: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    cited_by_count: int = 0
    imported: bool = False


class SearchPapersOutput(BaseModel):
    papers: list[PaperSearchResult]
    summary: str = ""


class ImportPaperInput(BaseModel):
    source: Literal["openalex"]
    source_id: str
    project_id: UUID


class ImportPaperOutput(BaseModel):
    job_id: UUID
    status: Literal["queued"]
    summary: str = "paper import queued"


class GetPaperInput(BaseModel):
    paper_id: UUID
    project_id: UUID | None = None


class GetPaperOutput(BaseModel):
    paper: dict
    summary: str = "paper loaded"


class CitationNeighborhoodInput(BaseModel):
    paper_id: UUID
    per_hop: int = Field(default=15, ge=1, le=50)
    include_shared_concepts: bool = True


class CitationNeighborhoodOutput(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    ranked_neighbors: list[dict] = Field(default_factory=list)
    summary: str = "citation neighborhood loaded"


class RetrieveEvidenceInput(BaseModel):
    project_id: UUID
    query: str
    seed_paper_ids: list[UUID] | None = None
    limit: int = Field(default=10, ge=1, le=30)


class EvidenceItem(BaseModel):
    paper_id: UUID
    title: str | None
    chunk_id: UUID | None = None
    text: str | None = None
    score: float
    retrieval_sources: list[str]
    reason: str
    in_project: bool
    is_stub: bool


class RetrieveEvidenceOutput(BaseModel):
    evidence: list[EvidenceItem]
    summary: str


class RankRelatedWorkInput(BaseModel):
    project_id: UUID
    section_text: str
    limit: int = Field(default=8, ge=1, le=20)


class RelatedWorkRecommendation(BaseModel):
    paper_id: UUID
    bibtex_key: str | None = None
    title: str | None
    reason: str
    evidence_snippets: list[str] = Field(default_factory=list)
    score: float
    is_stub: bool


class RankRelatedWorkOutput(BaseModel):
    recommendations: list[RelatedWorkRecommendation]
    summary: str


class SuggestBibtexInput(BaseModel):
    paper_ids: list[UUID]
    project_id: UUID


class BibtexEntry(BaseModel):
    paper_id: UUID
    bibtex_key: str
    bibtex: str


class SuggestBibtexOutput(BaseModel):
    entries: list[BibtexEntry]
    summary: str


class InspectLatexProjectInput(BaseModel):
    project_id: UUID
    paths: list[str] | None = None


class LatexFileView(BaseModel):
    path: str
    content: str
    version: int


class InspectLatexProjectOutput(BaseModel):
    files: list[LatexFileView]
    summary: str


class PatchLatexFileInput(BaseModel):
    project_id: UUID
    patch: dict  # validated against latex.patcher.Patch inside the tool


class PatchLatexFileOutput(BaseModel):
    status: str
    new_version: int | None = None
    summary: str


class CompileLatexInput(BaseModel):
    project_id: UUID
    main_file_path: str = "main.tex"


class CompileLatexOutput(BaseModel):
    compilation_id: UUID
    status: Literal["queued"]
    summary: str = "latex compilation queued"
```

Schema walkthrough:

- `SearchPapersInput/Output`: external or local paper search; used by UI and agent.
- `ImportPaperInput/Output`: enqueue import work instead of doing slow ingestion in the request.
- `GetPaper*`: inspect one canonical paper row.
- `CitationNeighborhood*`: graph-panel and graph-exploration tool shape.
- `RetrieveEvidence*`: raw HybridRetriever output exposed as a tool.
- `RankRelatedWork*`: citation-suggestion convenience wrapper around retrieval.
- `SuggestBibtex*`: turns papers into project-linked BibTeX entries and keys.
- `InspectLatexProject*`: gives the agent exact file text and version before patching.
- `PatchLatexFile*`: carries the anchor-based patch JSON into the safe patcher.
- `CompileLatex*`: queues Tectonic compilation.
- Every output has `summary` so the UI tool trace can show a concise row.

## `backend/app/agent/prompts.py`

```python
# System prompt is stable project behavior, not user-provided context.
SYSTEM_PROMPT = """You are CitePilot, a research-writing assistant. You help users write LaTeX
research papers using retrieved scholarly evidence.

Rules:
- Use only evidence returned by tools for factual claims about papers.
- Never invent citations or BibTeX keys. Only use keys returned by tools.
- When recommending citations, explain why each paper is relevant.
- Distinguish foundational papers, recent papers, and directly related papers.
- If retrieved evidence is weak or empty, say so plainly.
- When editing LaTeX, preserve the user's style; change only what was asked.
- Prefer concise responses.
"""


def build_user_context(
    project_name: str,
    active_file_path: str | None,
    selected_text: str | None,
    user_message: str,
) -> str:
    # Wrap runtime context and the user's actual request into one user message.
    return f"""Project: {project_name}
Active file: {active_file_path or "unknown"}

Selected text:
{selected_text or ""}

User request:
{user_message}
"""
```

Prompt walkthrough:

- The system prompt forbids invented citations and forces tool-grounded claims.
- `build_user_context()` makes the active file and selected text visible to the model.
- This is not hidden chain-of-thought; it is ordinary context given to the model.

## `backend/app/agent/llm/base.py`

The provider-neutral contract. `Message` must round-trip tool calls: an assistant message can carry `tool_calls`, and a `tool` message carries the result plus the `tool_call_id` it answers — providers can't link results to calls without that id. Each client translates this neutral form into its wire format (that's the whole adapter pattern).

```python
# dataclass gives simple immutable-ish transport objects.
from dataclasses import dataclass, field
# Any is needed for JSON schema and tool argument dictionaries.
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    # Tool name shown to the provider/model.
    name: str
    description: str
    input_schema: dict[str, Any]   # JSON schema, generated from the Pydantic input model


@dataclass(frozen=True)
class ToolCall:
    # Provider-generated call id; tool results must point back to it.
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """role: 'system' | 'user' | 'assistant' | 'tool'."""

    role: str
    # Text content for normal messages.
    content: str = ""
    # Assistant messages can request tool calls.
    tool_calls: list[ToolCall] = field(default_factory=list)   # assistant messages
    # Tool result messages identify which assistant call they answer.
    tool_call_id: str | None = None                            # tool messages


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    # Every provider adapter implements this one method.
    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse: ...
```

LLM contract walkthrough:

- Provider adapters translate this neutral shape into Anthropic/OpenAI wire formats.
- `tool_call_id` is essential: without it, providers cannot associate tool results with tool calls.
- The orchestrator depends only on `LLMClient`, so tests can use `FakeLLMClient`.

## `backend/app/agent/llm/fake.py`

Scriptable fake — the backbone of `test_agent_stream.py`. Queue up responses (including tool calls) and the orchestrator runs against them with zero network.

```python
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
```

## `backend/app/agent/llm/anthropic_client.py`

Raw httpx against the Messages API — no SDK dependency, and you learn the wire format. Translation rules: system messages → top-level `system` string; assistant tool calls → `tool_use` content blocks; `tool` messages → `tool_result` blocks inside a **user** message (consecutive tool results merge into one user message, as the API requires).

```python
# Any for provider payload dictionaries.
from typing import Any

# Direct HTTP client; no provider SDK required.
import httpx

from app.agent.llm.base import LLMResponse, Message, ToolCall, ToolSpec

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        # Fail fast if real provider is selected but not configured.
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required for the Anthropic client")
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=120)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        # Convert neutral messages into Anthropic's wire format.
        system, wire_messages = self._to_wire(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": wire_messages,
        }
        if system:
            payload["system"] = system
        if tools:
            # Anthropic tools use name/description/input_schema directly.
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
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        # Anthropic response content is a list of text/tool_use blocks.
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
        # Anthropic separates system prompt from normal messages.
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
```

Anthropic adapter walkthrough:

- System messages become one top-level `system` string.
- Assistant tool calls become `tool_use` blocks.
- Tool results become `tool_result` blocks inside user messages.
- The adapter is intentionally isolated so the orchestrator never knows Anthropic details.

## `backend/app/agent/llm/openai_client.py`

Same adapter, OpenAI wire format: tools are `function` objects, tool results are `role: "tool"` messages, and — the classic gotcha — `function.arguments` is a **JSON string**, not an object.

```python
# OpenAI stores tool call arguments as JSON strings, so json is required.
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
```

OpenAI adapter walkthrough:

- Tool specs become `{"type": "function", "function": ...}`.
- Assistant tool-call messages include a `tool_calls` array.
- Tool result messages use role `"tool"` plus `tool_call_id`.
- `json.loads(function.arguments)` is the common gotcha.

## `backend/app/agent/llm/providers.py`

```python
# Provider factories imported here keep app startup code simple.
from app.agent.llm.anthropic_client import AnthropicClient
from app.agent.llm.base import LLMClient
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.openai_client import OpenAIClient
from app.config import Settings


def create_llm_client(settings: Settings) -> LLMClient:
    # Tests should never call external LLM providers.
    if settings.APP_ENV == "test":
        return FakeLLMClient([])
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient(settings.LLM_API_KEY, settings.LLM_MODEL)
    if settings.LLM_PROVIDER == "openai":
        return OpenAIClient(settings.LLM_API_KEY, settings.LLM_MODEL)
    raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")
```

Provider walkthrough:

- One factory selects the adapter from settings.
- The rest of the backend depends on `LLMClient`, not vendor-specific classes.

## ⭐ `backend/app/agent/tools.py`

The single source of tool logic. FastAPI routes, the orchestrator, and the MCP server all call these functions through `ToolContext` — capabilities are a layer; agents and protocols are consumers.

```python
# Future annotations keep type hints flexible.
from __future__ import annotations

# arq pool enqueues slow jobs.
from arq.connections import ArqRedis
# Neo4j driver powers graph tools.
from neo4j import AsyncDriver
# Redis powers external API caches and clients.
from redis.asyncio import Redis
# select builds DB reads.
from sqlalchemy import select
# AsyncSession is the DB unit of work.
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import schemas as s
from app.agent.schemas import ToolError
from app.config import Settings
from app.db.models import (
    Author,
    Concept,
    Job,
    LatexCompilation,
    Paper,
    PaperAuthor,
    PaperConcept,
    Project,
    ProjectFile,
    ProjectPaper,
)
from app.graph import queries
from app.ingestion.bibtex import BibtexPaper, generate_fallback_bibtex, rekey_bibtex
from app.ingestion.crossref import CrossrefClient
from app.ingestion.normalize import normalize_openalex_work
from app.ingestion.openalex import OpenAlexClient
from app.ingestion.upsert import find_existing_paper, link_project_paper
from app.latex.patcher import PATCH_ADAPTER, PatchError, apply_patch
from app.latex.sanitizer import UnsafePathError, sanitize_project_path
from app.logging import get_logger
from app.retrieval.embeddings import create_embedding_client
from app.retrieval.explain import RetrievalFeatures, render_reason
from app.retrieval.graph_search import GraphSearch
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_search import VectorSearch

log = get_logger(__name__)


class ToolContext:
    """Runtime dependencies every tool needs. FastAPI, the MCP server, and the
    worker each build one — tool logic never knows who is calling it."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        neo4j: AsyncDriver,
        redis: Redis,
        arq_pool: ArqRedis | None = None,
    ):
        # Store dependencies; tools should not reach into FastAPI app.state directly.
        self.session = session
        self.settings = settings
        self.neo4j = neo4j
        self.redis = redis
        self.arq_pool = arq_pool


async def _require_project(ctx: ToolContext, project_id) -> Project:
    # Every project-scoped tool begins here; future auth hooks can live here too.
    project = await ctx.session.get(Project, project_id)
    if project is None:
        raise ToolError("not_found", f"Project {project_id} does not exist")
    return project


async def _author_names(ctx: ToolContext, paper_ids: list) -> dict:
    # Helper used by paper search/BibTeX tools to avoid duplicating author joins.
    if not paper_ids:
        return {}
    rows = (
        await ctx.session.execute(
            select(PaperAuthor.paper_id, Author.name)
            .join(Author, Author.id == PaperAuthor.author_id)
            .where(PaperAuthor.paper_id.in_(paper_ids))
            .order_by(PaperAuthor.author_order)
        )
    ).all()
    names: dict = {}
    for paper_id, name in rows:
        names.setdefault(paper_id, []).append(name)
    return names


async def search_papers(ctx: ToolContext, args: s.SearchPapersInput) -> s.SearchPapersOutput:
    # Tool implementation: same function is used by routes, agent, and MCP.
    results: list[s.PaperSearchResult] = []

    if args.source == "local":
        # Local search is a simple title search for POC.
        stmt = select(Paper).where(Paper.title.is_not(None), Paper.title.ilike(f"%{args.query}%"))
        if args.year_min:
            stmt = stmt.where(Paper.publication_year >= args.year_min)
        if args.year_max:
            stmt = stmt.where(Paper.publication_year <= args.year_max)
        stmt = stmt.order_by(Paper.cited_by_count.desc()).limit(args.limit)
        papers = (await ctx.session.execute(stmt)).scalars().all()
        names = await _author_names(ctx, [p.id for p in papers])
        for p in papers:
            results.append(
                s.PaperSearchResult(
                    paper_id=p.id,
                    external_id=p.openalex_id,
                    title=p.title,
                    year=p.publication_year,
                    authors=names.get(p.id, [])[:5],
                    abstract=(p.abstract or "")[:500] or None,
                    cited_by_count=p.cited_by_count or 0,
                    imported=not p.is_stub,
                )
            )
    else:
        # OpenAlex path hits the cached client, then normalizes results.
        client = OpenAlexClient(ctx.settings, ctx.redis)
        try:
            data = await client.search_works(args.query, limit=args.limit)
        finally:
            await client.aclose()
        for work in data.get("results", []):
            np = normalize_openalex_work(work)
            if args.year_min and np.publication_year and np.publication_year < args.year_min:
                continue
            if args.year_max and np.publication_year and np.publication_year > args.year_max:
                continue
            existing = await find_existing_paper(ctx.session, np)
            results.append(
                s.PaperSearchResult(
                    paper_id=existing.id if existing else None,
                    external_id=np.source_id,
                    title=np.title,
                    year=np.publication_year,
                    authors=[a.name for a in np.authors][:5],
                    abstract=(np.abstract or "")[:500] or None,
                    cited_by_count=np.cited_by_count or 0,
                    imported=bool(existing and not existing.is_stub),
                )
            )

    return s.SearchPapersOutput(
        papers=results,
        summary=f"found {len(results)} papers for '{args.query}' via {args.source}",
    )


async def import_paper(ctx: ToolContext, args: s.ImportPaperInput) -> s.ImportPaperOutput:
    # Import is slow, so the tool queues a job instead of doing work inline.
    await _require_project(ctx, args.project_id)
    if ctx.arq_pool is None:
        raise ToolError("unavailable", "job queue is not available in this context")

    job = Job(
        job_type="ingest_paper",
        input={
            "source": args.source,
            "source_id": args.source_id,
            "project_id": str(args.project_id),
        },
    )
    ctx.session.add(job)
    await ctx.session.commit()

    arq_job = await ctx.arq_pool.enqueue_job("ingest_paper_job", str(job.id))
    if arq_job is not None:
        job.queue_job_id = arq_job.job_id
        await ctx.session.commit()

    log.info("paper.import.queued", job_id=str(job.id), source_id=args.source_id)
    return s.ImportPaperOutput(job_id=job.id, status="queued")


async def get_paper(ctx: ToolContext, args: s.GetPaperInput) -> s.GetPaperOutput:
    paper = await ctx.session.get(Paper, args.paper_id)
    if paper is None:
        raise ToolError("not_found", f"Paper {args.paper_id} does not exist")

    names = await _author_names(ctx, [paper.id])
    concepts = [
        row[0]
        for row in (
            await ctx.session.execute(
                select(Concept.name)
                .join(PaperConcept, PaperConcept.concept_id == Concept.id)
                .where(PaperConcept.paper_id == paper.id)
            )
        ).all()
    ]
    in_project = False
    if args.project_id:
        in_project = (
            await ctx.session.execute(
                select(ProjectPaper).where(
                    ProjectPaper.project_id == args.project_id,
                    ProjectPaper.paper_id == paper.id,
                )
            )
        ).scalar_one_or_none() is not None

    return s.GetPaperOutput(
        paper={
            "paper_id": str(paper.id),
            "openalex_id": paper.openalex_id,
            "doi": paper.doi,
            "title": paper.title,
            "abstract": paper.abstract,
            "year": paper.publication_year,
            "venue": paper.venue_name,
            "cited_by_count": paper.cited_by_count,
            "is_stub": paper.is_stub,
            "authors": names.get(paper.id, []),
            "concepts": concepts,
            "in_project": in_project,
        },
        summary=f"loaded paper: {paper.title or paper.openalex_id or paper.id}",
    )


async def get_citation_neighborhood(
    ctx: ToolContext, args: s.CitationNeighborhoodInput
) -> s.CitationNeighborhoodOutput:
    seed = str(args.paper_id)
    neighborhood = await queries.two_hop_neighborhood(ctx.neo4j, seed, per_hop=args.per_hop)

    candidates = list(await queries.co_citation(ctx.neo4j, [seed], limit=10))
    candidates += await queries.bibliographic_coupling(ctx.neo4j, [seed], limit=10)
    if args.include_shared_concepts:
        candidates += await queries.shared_concepts(ctx.neo4j, [seed], limit=10)

    merged: dict[str, dict] = {}
    for cand in candidates:
        entry = merged.setdefault(
            cand.paper_id, {"signals": [], "features": {}, "score": 0.0}
        )
        entry["signals"].append(cand.signal)
        entry["features"].update(cand.features)
        entry["score"] += cand.score

    ranked_neighbors = []
    for paper_id, entry in sorted(merged.items(), key=lambda kv: -kv[1]["score"])[:10]:
        features = RetrievalFeatures(
            retrieval_sources=entry["signals"],
            shared_reference_count=entry["features"].get("shared_reference_count", 0),
            co_citation_count=entry["features"].get("co_citation_count", 0),
            shared_concept_names=tuple(entry["features"].get("shared_concept_names", ())),
        )
        ranked_neighbors.append(
            {"paper_id": paper_id, "signals": entry["signals"], "reason": render_reason(features)}
        )

    return s.CitationNeighborhoodOutput(
        nodes=neighborhood["nodes"],
        edges=neighborhood["edges"],
        ranked_neighbors=ranked_neighbors,
        summary=(
            f"neighborhood has {len(neighborhood['nodes'])} papers, "
            f"{len(neighborhood['edges'])} citation edges"
        ),
    )


async def retrieve_evidence(
    ctx: ToolContext, args: s.RetrieveEvidenceInput
) -> s.RetrieveEvidenceOutput:
    # This is the tool surface over the HybridRetriever from guide 04.
    await _require_project(ctx, args.project_id)
    embeddings = create_embedding_client(ctx.settings)
    try:
        retriever = HybridRetriever(
            embeddings=embeddings,
            vector_store=VectorSearch(ctx.session),
            graph=GraphSearch(ctx.neo4j),
            session=ctx.session,
        )
        results = await retriever.retrieve(
            project_id=args.project_id,
            query=args.query,
            seed_paper_ids=args.seed_paper_ids,
            limit=args.limit,
        )
    finally:
        aclose = getattr(embeddings, "aclose", None)
        if aclose:
            await aclose()

    evidence = [
        s.EvidenceItem(
            paper_id=r.paper_id,
            title=r.title,
            chunk_id=r.chunk_id,
            text=r.text,
            score=r.score,
            retrieval_sources=r.retrieval_sources,
            reason=r.reason,
            in_project=r.in_project,
            is_stub=r.is_stub,
        )
        for r in results
    ]
    sources = sorted({src for e in evidence for src in e.retrieval_sources})
    return s.RetrieveEvidenceOutput(
        evidence=evidence,
        summary=f"found {len(evidence)} candidate papers via {', '.join(sources) or 'no signals'}",
    )


async def rank_related_work(
    ctx: ToolContext, args: s.RankRelatedWorkInput
) -> s.RankRelatedWorkOutput:
    evidence_out = await retrieve_evidence(
        ctx,
        s.RetrieveEvidenceInput(
            project_id=args.project_id, query=args.section_text, limit=args.limit
        ),
    )
    paper_ids = [e.paper_id for e in evidence_out.evidence]
    key_rows = (
        await ctx.session.execute(
            select(ProjectPaper.paper_id, ProjectPaper.bibtex_key).where(
                ProjectPaper.project_id == args.project_id,
                ProjectPaper.paper_id.in_(paper_ids or [args.project_id]),
            )
        )
    ).all()
    keys = {paper_id: key for paper_id, key in key_rows}

    recommendations = [
        s.RelatedWorkRecommendation(
            paper_id=e.paper_id,
            bibtex_key=keys.get(e.paper_id),
            title=e.title,
            reason=e.reason,
            evidence_snippets=[e.text[:300]] if e.text else [],
            score=e.score,
            is_stub=e.is_stub,
        )
        for e in evidence_out.evidence
    ]
    return s.RankRelatedWorkOutput(
        recommendations=recommendations,
        summary=f"ranked {len(recommendations)} candidate citations",
    )


async def suggest_bibtex(ctx: ToolContext, args: s.SuggestBibtexInput) -> s.SuggestBibtexOutput:
    await _require_project(ctx, args.project_id)
    entries: list[s.BibtexEntry] = []
    crossref = CrossrefClient(ctx.settings, ctx.redis)
    try:
        for paper_id in args.paper_ids:
            paper = await ctx.session.get(Paper, paper_id)
            if paper is None:
                raise ToolError("not_found", f"Paper {paper_id} does not exist")
            if paper.is_stub:
                raise ToolError(
                    "is_stub",
                    f"Paper {paper_id} is a stub with incomplete metadata. Import it first.",
                )
            key = await link_project_paper(ctx.session, args.project_id, paper)

            bibtex = None
            if paper.doi:
                bibtex = await crossref.get_bibtex(paper.doi)   # publisher-quality, preferred
                if bibtex:
                    bibtex = rekey_bibtex(bibtex.strip() + "\n", key)
            if bibtex is None:                                   # fallback: generate + escape
                names = await _author_names(ctx, [paper.id])
                bibtex = generate_fallback_bibtex(
                    key,
                    BibtexPaper(
                        title=paper.title,
                        publication_year=paper.publication_year,
                        venue_name=paper.venue_name,
                        doi=paper.doi,
                        url=paper.url,
                        authors=names.get(paper.id, []),
                    ),
                )
            entries.append(s.BibtexEntry(paper_id=paper.id, bibtex_key=key, bibtex=bibtex))
    finally:
        await crossref.aclose()

    await ctx.session.commit()   # persist any new project_papers links
    return s.SuggestBibtexOutput(
        entries=entries, summary=f"prepared {len(entries)} BibTeX entries"
    )


async def inspect_latex_project(
    ctx: ToolContext, args: s.InspectLatexProjectInput
) -> s.InspectLatexProjectOutput:
    await _require_project(ctx, args.project_id)
    stmt = select(ProjectFile).where(ProjectFile.project_id == args.project_id)
    if args.paths:
        try:
            safe = [sanitize_project_path(p) for p in args.paths]
        except UnsafePathError as exc:
            raise ToolError("unsafe_path", str(exc))
        stmt = stmt.where(ProjectFile.path.in_(safe))
    files = (await ctx.session.execute(stmt.order_by(ProjectFile.path))).scalars().all()
    return s.InspectLatexProjectOutput(
        files=[
            s.LatexFileView(path=f.path, content=f.content, version=f.version) for f in files
        ],
        summary=f"read {len(files)} files: {', '.join(f.path for f in files)}",
    )


async def patch_latex_file(
    ctx: ToolContext, args: s.PatchLatexFileInput
) -> s.PatchLatexFileOutput:
    """Direct application — used by MCP and by the web accept endpoint. The web
    orchestrator intercepts this tool and turns it into a proposal instead."""
    await _require_project(ctx, args.project_id)
    try:
        # Validate dict into ReplaceTextPatch or InsertAfterPatch.
        patch = PATCH_ADAPTER.validate_python(args.patch)
    except Exception as exc:
        raise ToolError("invalid_arguments", f"patch failed validation: {exc}")
    try:
        result = await apply_patch(ctx.session, args.project_id, patch)
    except PatchError as exc:
        raise ToolError(exc.code, exc.message, exc.details)
    return s.PatchLatexFileOutput(
        status=result["status"],
        new_version=result["new_version"],
        summary=f"applied patch to {result['path']} -> version {result['new_version']}",
    )


async def compile_latex(ctx: ToolContext, args: s.CompileLatexInput) -> s.CompileLatexOutput:
    # Compilation is slow and sandboxed in worker, so enqueue it.
    await _require_project(ctx, args.project_id)
    if ctx.arq_pool is None:
        raise ToolError("unavailable", "job queue is not available in this context")
    try:
        safe_main = sanitize_project_path(args.main_file_path)
    except UnsafePathError as exc:
        raise ToolError("unsafe_path", str(exc))

    compilation = LatexCompilation(project_id=args.project_id, main_file_path=safe_main)
    ctx.session.add(compilation)
    await ctx.session.commit()
    await ctx.arq_pool.enqueue_job("compile_latex_job", str(compilation.id))
    log.info("latex.compile.queued", compilation_id=str(compilation.id))
    return s.CompileLatexOutput(compilation_id=compilation.id, status="queued")
```

One addition this file needs in `latex/patcher.py` — add at the bottom (after the `Patch` union):

```python
from pydantic import TypeAdapter

PATCH_ADAPTER: TypeAdapter[Patch] = TypeAdapter(Patch)
```

Tool walkthrough:

- `ToolContext` is dependency injection for tools; it keeps capabilities independent of FastAPI/MCP.
- Tools are narrow and typed. There is no arbitrary SQL, Cypher, shell, or filesystem tool.
- `search_papers` has local and OpenAlex paths but returns one common output shape.
- `import_paper` and `compile_latex` queue durable jobs instead of blocking the agent.
- `retrieve_evidence` is the GraphRAG tool; `rank_related_work` formats it for citation suggestions.
- `suggest_bibtex` both links papers to a project and returns stable citation keys.
- `patch_latex_file` delegates safety to the anchor-based patcher.

## ⭐ `backend/app/agent/tool_registry.py`

Tools registered once with name, **description (the model reads this — a vague description is a routing bug)**, Pydantic input/output models, and the implementation. `specs()` derives JSON schema from the input models, so validation and documentation cannot drift apart. The web agent and MCP consume this same registry.

```python
# Callable/Awaitable type the core async tool functions.
from collections.abc import Awaitable, Callable
# dataclass for registry metadata.
from dataclasses import dataclass

# BaseModel is the parent type of all input/output schemas.
from pydantic import BaseModel, ValidationError

from app.agent import schemas as s
from app.agent import tools
from app.agent.llm.base import ToolSpec
from app.agent.schemas import ToolError
from app.agent.tools import ToolContext


@dataclass(frozen=True)
class ToolDefinition:
    # Metadata and implementation for one model-callable tool.
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    fn: Callable[[ToolContext, BaseModel], Awaitable[BaseModel]]


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        # Store runtime dependencies once; every tool call uses this context.
        self.ctx = ctx
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        # Duplicate names would make model routing ambiguous.
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        self._tools[definition.name] = definition

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        # Convert Pydantic input models into provider-neutral tool specs.
        return [
            ToolSpec(
                name=d.name,
                description=d.description,
                input_schema=d.input_model.model_json_schema(),
            )
            for d in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict) -> BaseModel:
        # Find registered tool by model-requested name.
        definition = self._tools.get(name)
        if definition is None:
            raise ToolError("unknown_tool", f"No tool named '{name}'. Available: {self.names()}")
        try:
            # Validate raw JSON arguments before executing Python code.
            args = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError(
                "invalid_arguments",
                f"Arguments for '{name}' failed validation: {exc.errors()[:3]}",
            )
        return await definition.fn(self.ctx, args)


def build_default_registry(ctx: ToolContext) -> ToolRegistry:
    registry = ToolRegistry(ctx)
    for definition in [
        ToolDefinition(
            name="search_papers",
            description=(
                "Search scholarly papers. source='openalex' searches the global OpenAlex "
                "index; source='local' searches papers already imported into CitePilot. "
                "Returns titles, years, authors, abstracts, citation counts, and whether "
                "each paper is already imported."
            ),
            input_model=s.SearchPapersInput,
            output_model=s.SearchPapersOutput,
            fn=tools.search_papers,
        ),
        ToolDefinition(
            name="import_paper",
            description=(
                "Import a paper by its OpenAlex ID into the project. Stores metadata, "
                "creates stub records for all its references, mirrors the citation graph, "
                "and embeds the abstract. Returns a job_id to poll."
            ),
            input_model=s.ImportPaperInput,
            output_model=s.ImportPaperOutput,
            fn=tools.import_paper,
        ),
        ToolDefinition(
            name="get_paper",
            description="Fetch one imported paper's full metadata, authors, concepts, and whether it is in the project.",
            input_model=s.GetPaperInput,
            output_model=s.GetPaperOutput,
            fn=tools.get_paper,
        ),
        ToolDefinition(
            name="get_citation_neighborhood",
            description=(
                "Explore the local citation graph around a paper: nodes/edges for "
                "visualization plus neighbors ranked by co-citation, shared references, "
                "and shared concepts, each with a human-readable reason."
            ),
            input_model=s.CitationNeighborhoodInput,
            output_model=s.CitationNeighborhoodOutput,
            fn=tools.get_citation_neighborhood,
        ),
        ToolDefinition(
            name="retrieve_evidence",
            description=(
                "Hybrid GraphRAG retrieval for a query or paragraph: fuses semantic "
                "similarity with citation-graph signals (co-citation, bibliographic "
                "coupling, shared concepts). Use this to find citation-worthy papers. "
                "Returns ranked evidence with supporting text and reasons."
            ),
            input_model=s.RetrieveEvidenceInput,
            output_model=s.RetrieveEvidenceOutput,
            fn=tools.retrieve_evidence,
        ),
        ToolDefinition(
            name="rank_related_work",
            description=(
                "Recommend citations for a LaTeX section or paragraph. Runs hybrid "
                "retrieval on the text and returns ranked recommendations with reasons, "
                "evidence snippets, and BibTeX keys for papers already in the project."
            ),
            input_model=s.RankRelatedWorkInput,
            output_model=s.RankRelatedWorkOutput,
            fn=tools.rank_related_work,
        ),
        ToolDefinition(
            name="suggest_bibtex",
            description=(
                "Produce BibTeX entries (Crossref publisher data when a DOI exists, "
                "escaped fallback otherwise) and stable citation keys for papers, "
                "linking them to the project. Use the returned keys in \\cite{}."
            ),
            input_model=s.SuggestBibtexInput,
            output_model=s.SuggestBibtexOutput,
            fn=tools.suggest_bibtex,
        ),
        ToolDefinition(
            name="inspect_latex_project",
            description="Read the project's LaTeX files (optionally specific paths). Returns path, content, and version for each.",
            input_model=s.InspectLatexProjectInput,
            output_model=s.InspectLatexProjectOutput,
            fn=tools.inspect_latex_project,
        ),
        ToolDefinition(
            name="patch_latex_file",
            description=(
                "Edit a project file with an anchor-based patch: either "
                "{operation:'replace_text', path, base_version, old_text, new_text} or "
                "{operation:'insert_after', path, base_version, anchor_text, new_text}. "
                "The anchor must occur exactly once in the current file content."
            ),
            input_model=s.PatchLatexFileInput,
            output_model=s.PatchLatexFileOutput,
            fn=tools.patch_latex_file,
        ),
        ToolDefinition(
            name="compile_latex",
            description="Compile the project's LaTeX to PDF with Tectonic. Returns a compilation_id to poll for status, logs, and the PDF.",
            input_model=s.CompileLatexInput,
            output_model=s.CompileLatexOutput,
            fn=tools.compile_latex,
        ),
    ]:
        registry.register(definition)
    return registry
```

Registry walkthrough:

- Tool descriptions are part of the prompt; write them for the model.
- JSON schema is derived from Pydantic models so validation and docs do not drift.
- `execute()` is the one choke point for unknown tools and invalid args.
- `build_default_registry()` is where the ten MVP tools are declared in one place.

## ⭐ `backend/app/agent/orchestrator.py`

The bounded tool loop. Properties that make it production-grade: max 8 iterations; every tool result **including errors** goes back into the conversation so the model self-corrects (`anchor_ambiguous: found 3 matches` → model retries with a longer anchor); every call persists to `tool_calls` (results truncated to 4 KB); everything streams to the UI as events.

```python
# Future annotations for type hints.
from __future__ import annotations

# json serializes tool results into messages and truncation checks.
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
from app.latex.patcher import PATCH_ADAPTER, PatchError, preview_patch
from app.logging import get_logger

log = get_logger(__name__)

# Hard loop bound: agents must not run forever.
MAX_TOOL_ITERATIONS = 8
# Tool call results can be large; DB storage is capped.
RESULT_TRUNCATE_BYTES = 4096

EmitFn = Callable[[str, dict], Awaitable[None]]


@dataclass
class AgentTurnContext:
    # Request-specific context passed to the orchestrator.
    project_id: UUID
    project_name: str = ""
    active_file_path: str | None = None
    selected_text: str | None = None
    auto_apply_patches: bool = False   # False in the web UI; True over MCP


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
    # Build initial message list: system prompt, history, current contextual user message.
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
    await db.commit()

    final_text = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        # Ask the model what to say/do next, with current tool specs.
        response = await llm.complete(messages, tools=registry.specs())

        if response.text:
            # Stream text to UI as a message_delta event.
            final_text = response.text
            await emit("message_delta", {"text": response.text})

        messages.append(
            Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )
        if not response.tool_calls:
            # No tool calls means the turn is complete.
            break

        for call in response.tool_calls:
            # Make the tool call visible before executing it.
            await emit("tool_call", {"tool_name": call.name, "arguments": call.arguments})
            record = ToolCallRecord(
                session_id=agent_session_id, tool_name=call.name, arguments=call.arguments
            )
            db.add(record)
            await db.commit()

            if call.name == "patch_latex_file" and not turn.auto_apply_patches:
                # Web UI path: propose patch for human approval.
                payload = await _propose_patch(db, turn, call, record, emit)
            else:
                # Normal path: execute tool immediately.
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
    db: AsyncSession, registry: ToolRegistry, call, record: ToolCallRecord, emit: EmitFn
) -> dict:
    try:
        # Registry validates args and calls the core tool.
        output = await registry.execute(call.name, call.arguments)
    except ToolError as exc:
        await _finish_record(db, record, "failed", None, f"{exc.code}: {exc.message}")
        await emit("tool_result", {"tool_name": call.name, "error": exc.code, "message": exc.message})
        log.warning("agent.tool.failed", tool=call.name, code=exc.code)
        return exc.as_tool_result()

    payload = output.model_dump(mode="json")
    await _finish_record(db, record, "completed", truncate_result(payload), None)
    await emit("tool_result", {"tool_name": call.name, "summary": payload.get("summary") or "ok"})
    log.info("agent.tool.completed", tool=call.name)

    if call.name == "rank_related_work":
        # Special event lets UI render citation cards directly.
        await emit("citation_suggestions", {"recommendations": payload.get("recommendations", [])})
    return payload


async def _propose_patch(
    db: AsyncSession, turn: AgentTurnContext, call, record: ToolCallRecord, emit: EmitFn
) -> dict:
    """Web-UI flow: preview instead of apply. The pending tool_calls row is the
    handle the accept endpoint uses to apply the patch after user approval."""
    try:
        # Validate and preview patch without mutating files.
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
```

Orchestrator walkthrough:

- The loop is bounded by `MAX_TOOL_ITERATIONS`.
- Every model-requested tool call is emitted, logged, executed/proposed, and fed back as a tool message.
- Tool failures are not hidden; they become structured data the model can use to retry.
- Patch calls are intercepted for web UI approval unless `auto_apply_patches=True`.
- Results are truncated before storage so `tool_calls` does not become a giant blob table.

## Acceptance checks

```bash
docker compose exec backend pytest app/tests/test_agent_stream.py
```

Expected event order: `message_delta* → tool_call → tool_result → message_delta* → done`. Manual (after guide 08): select text → ask for citations → trace shows `inspect_latex_project → retrieve_evidence → rank_related_work` → suggestion cards carry graph-grounded reasons → every call has a `tool_calls` row with truncated results.

---

## Changes (review pass, 2026-07-05)

The following issues were found in the implemented files and fixed directly (each fix site is marked with a `# fix:` comment in the code):

1. **`backend/app/agent/llm/base.py` — the `Message` dataclass was missing the `content: str = ""` field.** This is the single most load-bearing field in the module: the orchestrator builds `Message(role="system", content=SYSTEM_PROMPT)`, `_load_history` builds `Message(role=..., content=...)`, both wire adapters read `message.content`, and tool results are sent as `Message(role="tool", content=json.dumps(...))`. Without the field, every one of those constructions raised `TypeError: unexpected keyword argument 'content'`, so no agent turn could even start. Added the field between `role` and `tool_calls`.

2. **`backend/app/agent/llm/anthropic_client.py` — HTTP timeout was 20 seconds instead of 120.** A single agent iteration with tools and history routinely takes longer than 20s on the provider side; the OpenAI adapter already used 120s. A too-short timeout turns normal long completions into `httpx.ReadTimeout` failures mid-turn. Set to 120 to match the guide and the sibling adapter.

3. **`backend/app/agent/tools.py` — `_require_project` called `ctx.session.execute.get(Project, project_id)`.** `.get()` is a method on `AsyncSession` itself, not on the (un-called) `execute` method object, so this raised `AttributeError` for every project-scoped tool — which is 8 of the 10 tools (`import_paper`, `retrieve_evidence`, `suggest_bibtex`, `inspect_latex_project`, `patch_latex_file`, `compile_latex`, …). Fixed to `ctx.session.get(...)`.

4. **`backend/app/agent/orchestrator.py` — two bugs:**
   - `await db.commit` (no parentheses) after adding the user's `AgentMessage`. This awaits the bound method object rather than calling it — a `TypeError` at the very start of `run_agent_turn`, before the first LLM call. Fixed to `await db.commit()`.
   - In `_execute_call`'s `ToolError` handler, `_finish_record(...)` was called twice in a row with identical arguments. Harmless in effect (the second call re-commits the same values) but wrong; removed the duplicate.

No changes were needed to `schemas.py`, `prompts.py`, `llm/fake.py`, `llm/openai_client.py`, `llm/providers.py`, or `tool_registry.py` — they match this guide. (`PATCH_ADAPTER`, which this guide says to add to `latex/patcher.py`, was already present there.)
