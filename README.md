# CitePilot

**LaTeX writing with citation-aware GraphRAG.** An Overleaf-style workspace where an AI research agent recommends citations by fusing semantic search with the citation graph itself — because the papers you must cite are often structurally related to your work without being textually similar.

## What it does

- **Write** LaTeX in a versioned CodeMirror editor; compile to PDF with sandboxed Tectonic.
- **Import** papers from OpenAlex; every reference becomes a stub row + citation edge immediately, so the graph is dense from the first import.
- **Retrieve** citation-worthy papers for any paragraph: five independent ranked lists (vector similarity + co-citation + bibliographic coupling + shared concepts + citation neighbors) fused with Reciprocal Rank Fusion.
- **Explain** every recommendation with reasons computed from graph features — never LLM-generated, so they can't be hallucinated.
- **Edit safely**: the agent proposes anchor-based patches that a human approves in the UI; wrong anchors fail loudly instead of corrupting files.
- **Expose** the same ten typed tools to any MCP client (Claude Desktop, MCP Inspector) with zero duplicated logic.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Vite + React 19 + TypeScript, TanStack Query, Zustand, CodeMirror, XYFlow, Tailwind v4 |
| API | FastAPI (async), SSE streaming agent |
| Truth store | Postgres 16 + pgvector (HNSW) |
| Graph mirror | Neo4j 5 (derived — rebuildable via `make resync-graph`) |
| Queue / cache | Redis + arq workers |
| LaTeX | Tectonic (network-free, bundle pre-warmed at image build) |
| LLM | Provider-agnostic adapters (Anthropic / OpenAI), bounded 8-iteration tool loop |

## Quickstart

```bash
cp .env.example .env   # then fill in: OPENALEX_MAILTO, LLM_API_KEY, EMBEDDING_API_KEY
make up                # docker compose up --build (first build takes a few minutes)
make migrate           # alembic upgrade head (run once, in a second terminal)
open http://localhost:3000
```

Verify: `curl http://localhost:8000/api/health` → all stores `"ok"`.

## Development

```bash
make test-backend      # pytest inside the backend container
make resync-graph      # wipe Neo4j and rebuild it from Postgres (proves it's derived)
make logs              # tail all services
cd apps/web && pnpm dev  # frontend outside Docker if preferred
```

MCP server (stdio): `npx @modelcontextprotocol/inspector docker compose exec -T backend python -m app.mcp_server.server`

## Architecture in one paragraph

Postgres is the single source of truth; Neo4j is a derived mirror used only for relationship traversal. Ingestion normalizes every provider into one DTO, dedupes by DOI → provider ID → title+year, and enriches existing rows in place (stubs promote without losing their UUID or edges). Retrieval keeps five signals as independent ranked lists until rank-only RRF fuses them — no scale-mixing, one parameter. The agent is a bounded tool loop where tool errors are data fed back to the model, every call is audited to `tool_calls`, and file edits are exact-anchor patches gated by version checks and (in the web UI) human approval.
