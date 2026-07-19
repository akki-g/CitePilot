# Backend Changes — Chat Latency Fix, LLM Streaming, Paper Detail API

_Date: 2026-07-05_

This document covers every backend change made in this pass. The driving
problems were: (1) agent chats appeared to "never send" — the request hung
indefinitely with no response; (2) even when working, the chat only rendered
text after the entire LLM response finished; (3) the frontend graph needed a
richer per-paper API to show abstracts and citations on click.

---

## 1. Root cause of the chat hang (`app/api/routes/agent.py`)

**Symptom:** sending a chat message spun forever. No error, no text, nothing.

**Cause:** in `POST /api/agent/stream`, the LLM client was constructed
*outside* the `try` block of the background task:

```python
async def run() -> None:
    llm = create_llm_client(settings)   # <-- raises before try/except/finally
    try:
        ...
    finally:
        await queue.put(None)           # sentinel that ends the SSE stream
```

`create_llm_client` raises `ValueError` when `LLM_API_KEY` is empty (which it
currently is in `.env`). Because the exception fired before the `try`, the
`finally` never ran, so neither an `error` event nor the `None` end-of-stream
sentinel was ever enqueued. The SSE generator then blocked forever on
`queue.get()`, and the browser saw a connection that never produced a byte —
i.e. "chats take too long to send."

**Fix:**

- `llm = None` is assigned first, and `create_llm_client` now runs *inside*
  the `try`. Any configuration error is emitted to the client as a normal
  `error` SSE event, and the sentinel always fires in `finally`.
- The `finally` block guards `aclose` with `llm is not None`.
- A new **`session` event is emitted as the first frame** of every stream,
  carrying the `session_id`. The UI gets an instant acknowledgment (and can
  bind the session id for follow-up turns) before the first slow LLM call.

**Verified:** with no API key configured, `POST /api/agent/stream` now returns
immediately with `event: session` followed by
`event: error — "LLM_API_KEY and LLM_MODEL are required for the anthropic client"`
and closes the stream cleanly.

> **Action needed:** chat still requires `LLM_API_KEY` to be set in `.env`
> (and `EMBEDDING_API_KEY` for `retrieve_evidence`/hybrid retrieval). The
> failure is now instant and visible in the UI instead of a silent hang.

## 2. True token streaming (`app/agent/llm/anthropic_client.py`)

Previously `AnthropicClient.complete()` did a single blocking POST with
`max_tokens: 4096` and returned only when the entire response was generated.
For a tool-using turn this meant the user stared at a spinner for the full
duration of every LLM round-trip.

**Changes:**

- Added `stream()`, which calls the Messages API with `"stream": true`,
  parses the SSE event stream (`content_block_start` / `content_block_delta`
  / `content_block_stop`), and invokes an `on_text(chunk)` callback for every
  `text_delta` as it arrives. Tool-use blocks are assembled from
  `input_json_delta` fragments and returned as structured `ToolCall`s.
- `complete()` is now a thin wrapper over `stream(..., on_text=None)`, so
  both paths share one wire-format implementation.
- **Prompt caching enabled**: the system prompt is sent as a content block
  with `cache_control: {"type": "ephemeral"}`, and the last tool definition is
  also marked. Everything up to and including the tool list is cached by
  Anthropic between iterations and turns, cutting time-to-first-token for
  every request after the first (the tool loop re-sends the same prefix up to
  8 times per turn, so this is a large win).
- Replaced the flat 120 s timeout with granular `httpx.Timeout(connect=10,
  read=120, write=30, pool=10)`. With streaming, `read` applies per-chunk
  rather than per-response, so a healthy stream can run arbitrarily long
  while a stalled connection still fails fast.
- Streaming error frames (`event.type == "error"`) and non-2xx responses
  raise with the API's message included, instead of a bare status error.

## 3. Orchestrator streams deltas (`app/agent/orchestrator.py`)

- The tool loop now probes the client for `stream()` (via `getattr`) and
  passes an `on_text` callback that forwards each chunk to the UI as a
  `message_delta` SSE event. Providers without `stream()` (OpenAI adapter,
  the `FakeLLMClient` used in tests) keep the old behavior: one
  `message_delta` with the full text. No test changes were needed.
- **Bug fix:** `final_text = response.text` overwrote earlier iterations'
  text, so when the model wrote prose both before and after a tool call, only
  the last segment was persisted to `agent_messages`. Text segments are now
  accumulated and stored joined with blank lines.

## 4. Streaming-capable client protocol (`app/agent/llm/base.py`)

- Added `OnTextDelta = Callable[[str], Awaitable[None]]` and a
  `StreamingLLMClient` protocol (superset of `LLMClient` with `stream()`).
  The orchestrator's `getattr` probe keeps this fully backward compatible —
  implementing `stream` is opt-in per provider.

## 5. New endpoint: `GET /api/papers/{paper_id}` (`app/api/routes/papers.py`)

Backs the new "click a graph node → see the paper" panel in the frontend.

- Reuses the existing `get_paper` agent tool for the core lookup (title,
  abstract, year, venue, `cited_by_count`, authors in order, concepts,
  `is_stub`, `in_project`), translating `ToolError` → HTTP 404.
- Adds `url` and `pdf_url` from the `papers` row.
- With `?project_id=<uuid>`, also returns the project's `bibtex_key` for the
  paper and a rendered BibTeX entry (via the existing
  `generate_fallback_bibtex` helper), so the UI can offer copy-paste-ready
  citations.

Example:

```
GET /api/papers/{paper_id}?project_id={project_id}
→ { title, abstract, year, venue, cited_by_count, authors[], concepts[],
    doi, url, pdf_url, is_stub, in_project, bibtex_key, bibtex }
```

## 6. Agent no longer hallucinates project IDs

**Symptom:** asking the agent to write/edit anything made it call
`inspect_latex_project` with a made-up project id (the RFC example UUID
`550e8400-e29b-41d4-a716-446655440000`), fail with "project does not exist,"
and then ask the user for their project ID.

**Cause:** every project tool takes a required `project_id`, but the model was
never told the real one — `build_user_context` only included the project
*name*. The model's only options were to invent an id or ask.

**Fix (two layers):**

- `app/agent/orchestrator.py` + `app/agent/tool_registry.py`: before a tool
  call is recorded or executed, the orchestrator now **overwrites
  `project_id` with the active turn's project** for every tool whose input
  model declares one (`ToolRegistry.is_project_scoped`). A web session is
  scoped to one project, so a hallucinated or stale id can neither fail the
  call nor touch another project. This also guarantees stored
  `patch_latex_file` proposals carry the right id for the accept endpoint.
- `app/agent/prompts.py`: `build_user_context` now includes a
  `Project ID: <uuid>` line, and the system prompt tells the model tool calls
  are auto-scoped and it must never ask the user for project/file ids.

Covered by a new assertion in `test_agent_stream.py`: a tool call sent with
empty arguments is recorded with the turn's `project_id` pinned.

## 7. Embedding rate limits no longer kill the agent turn

**Symptom:** asking the agent to write something produced a raw "client error
'429 Too Many Requests'" — the OpenAI embeddings call inside
`retrieve_evidence`/`rank_related_work` was throttled and the unhandled
exception ended the whole SSE stream.

**Changes (`app/retrieval/embeddings.py`, `app/agent/tools.py`):**

- `OpenAIEmbeddingClient.embed_texts` now retries 429/5xx up to 4 attempts
  with exponential backoff + jitter, honoring the `Retry-After` header when
  present. Exhausted retries raise a typed `EmbeddingRateLimitError`.
- New `CachedEmbeddingClient`: a Redis read-through cache keyed on
  `model + sha1(text)` (24 h TTL). The agent tool path uses it
  (`create_embedding_client(settings, redis=ctx.redis)`), so re-embedding the
  same paragraph across tool-loop iterations or repeated questions never hits
  the provider twice. Cache failures degrade silently to direct calls.
- `retrieve_evidence` maps `EmbeddingRateLimitError` →
  `ToolError("rate_limited", ...)` and other provider errors →
  `ToolError("embedding_failed", ...)`. Tool errors flow back into the
  conversation as data, so the model tells the user what happened and the
  stream survives. The import worker benefits from the same retries.

## 8. New endpoint: `GET /api/graph/project/{project_id}`

Backs the graph tab's new default "all project papers" overview: returns every
paper in the project (id, title, year, cited_by_count, bibtex_key) plus all
CITES edges *among project papers*, straight from Postgres (`citations`
table) with no Neo4j round-trip. Selecting a bibliography entry still uses the
Neo4j two-hop `/api/graph/neighborhood` for the focused view.

## 9. Verification

- `pytest app/tests` inside the backend container: **35 passed**.
- Manual SSE smoke test of `/api/agent/stream` (see §1).
- Manual check of `/api/papers/{id}?project_id=...` against the seeded demo
  project (returns full metadata + BibTeX).

### Note observed while testing (not changed)

`app/tests/conftest.py` builds its engine from the same settings as the app,
so running pytest inside the backend container writes `test-project` rows into
the dev database. The rows created by this run were deleted afterwards.
Pointing tests at a separate database (or wrapping them in rollbacks) would be
a good follow-up.

## Frontend contract changes (for reference)

New/changed SSE events consumed by the web app:

| Event | Payload | When |
| --- | --- | --- |
| `session` *(new)* | `{session_id}` | First frame of every stream |
| `message_delta` | `{text}` | Now fired per token chunk (Anthropic), not per full response |
| `tool_call` / `tool_result` / `patch_proposal` / `citation_suggestions` / `done` / `error` | unchanged | unchanged |
