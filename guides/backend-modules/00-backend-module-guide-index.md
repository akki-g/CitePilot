# Backend Module Guide Index

Every file in these guides is **complete, exact code — type it as-is and it runs**. The architecture decisions are made and explained in place; your job is to type, read the "why" notes, and run the acceptance checks. Nothing is left as a contract, TODO, or `NotImplementedError`.

## Order

0. [../01-bootstrap-and-docker.md](../01-bootstrap-and-docker.md) — repo, compose, Dockerfiles, `pyproject.toml` (prerequisite for everything)
1. `01-foundation-and-db.md` — settings, logging, models, Alembic, lifespan
2. `02-graph.md` — Neo4j client, constraints, ⭐ Cypher queries, ⭐ sync + resync
3. `03-ingestion.md` — OpenAlex/Crossref/S2 clients, ⭐ normalize, ⭐ upsert + stubs, BibTeX
4. `04-retrieval.md` — chunking, embeddings, vector search, ⭐ RRF fusion, ⭐ hybrid retriever
5. `05-latex.md` — sanitizer, ⭐ anchor patcher, sandboxed compiler, Tectonic image
6. `06-agent-and-llm.md` — schemas, LLM adapters (Anthropic/OpenAI/Fake), ⭐ tools, ⭐ registry, ⭐ orchestrator
7. `07-mcp-server.md` — FastMCP server, ⭐ ten tool wrappers
8. `08-api-and-workers.md` — all routes (incl. SSE streaming + patch accept), arq worker + jobs
9. `09-tests-and-fixtures.md` — complete test suite + fixtures

## ⭐ legend

⭐ = core learning file — this is the interview material. Type it slowly, understand every line, and use guide 09's matching test as a self-check (the rhythm: delete the file, rewrite it from memory, make its test pass). Everything unmarked is plumbing: type it fast, read the notes once.

| Module | ⭐ files | What they teach |
|---|---|---|
| `graph/` | `queries.py`, `sync.py` | Co-citation, bibliographic coupling, per-hop budgets, derived-store sync |
| `ingestion/` | `normalize.py`, `upsert.py` | Entity resolution, DOI normalization, stub papers |
| `retrieval/` | `fusion.py`, `hybrid.py` | Reciprocal Rank Fusion, GraphRAG orchestration |
| `latex/` | `patcher.py` | Safe agent write-actions: anchors, versions, loud failures |
| `agent/` | `tools.py`, `tool_registry.py`, `orchestrator.py` | Typed tools, bounded tool loop, errors-as-data, observability |
| `mcp_server/` | `tools.py` | MCP wrappers, docstring discipline, capabilities-as-a-layer |

## Cross-cutting conventions (all guides assume these)

- **`ToolContext(session, settings, neo4j, redis, arq_pool)`** is the one dependency bundle. Routes, the orchestrator, the MCP server, and workers each build it; tool logic never knows its caller.
- **Postgres is the source of truth; Neo4j is a rebuildable mirror.** Commit Postgres **before** mirroring to Neo4j. `make resync-graph` proves derivability.
- **The ORM class for the `tool_calls` table is `ToolCallRecord`** — `ToolCall` is the LLM-layer dataclass. Two things, two names.
- **Graph boundary uses string UUIDs** (Neo4j properties are strings); Python converts at the edges.
- **Raw SQL + pgvector + asyncpg**: pass embeddings as string literals with `CAST(:param AS vector)` (see `vector_search.py`). ORM writes through the `Vector` column type are fine.
- **Web patches are proposals** (`patch_proposal` event → accept endpoint); MCP patches apply directly with versioning as the safety net.
- **Log events** are stable dotted names (`paper.import.started`, `agent.tool.failed`) with fields, never f-strings.
- **Tests never call external APIs.** Fakes (`FakeLLMClient`, `FakeEmbeddingClient`) and JSON fixtures only.

## Dependency direction (never violate)

```text
api/routes  -> agent/tools or services
mcp_server  -> agent/tools
workers     -> ingestion/retrieval/latex/graph services
agent       -> retrieval/ingestion/latex service functions
retrieval   -> db + graph
ingestion   -> db + graph + external clients (+ retrieval.chunking, a pure helper)
graph       -> Neo4j driver + Postgres rows
db          -> SQLAlchemy models/session only
```

Direction walkthrough:

- `api/routes -> agent/tools or services`: HTTP routes should validate requests and delegate; they should not contain business logic.
- `mcp_server -> agent/tools`: MCP exposes the same capabilities as the web agent, so wrappers call the same core tools.
- `workers -> ingestion/retrieval/latex/graph services`: slow jobs reuse service code instead of duplicating route logic.
- `agent -> retrieval/ingestion/latex service functions`: the agent calls typed capabilities, not databases or shell commands directly.
- `retrieval -> db + graph`: GraphRAG reads canonical metadata from Postgres and relationship signals from Neo4j.
- `ingestion -> db + graph + external clients`: ingestion is allowed to fetch provider data, write canonical rows, and trigger graph sync.
- `graph -> Neo4j driver + Postgres rows`: graph code mirrors rows and runs Cypher, but it does not know about HTTP or MCP.
- `db -> SQLAlchemy models/session only`: the database layer is the bottom; it should not import application workflows above it.

Lower layers never import FastAPI routes, MCP wrappers, or worker definitions.

## Definition of done (backend POC)

1. `make up` from a cold clone; migrations apply; health is green.
2. Import a paper → paper + stub rows + citation edges in Postgres, mirrored nodes/edges in Neo4j, embedded chunk in pgvector.
3. "Enrich graph" promotes stubs in place (same UUIDs, edges survive).
4. `retrieve_evidence` returns ranked results with `retrieval_sources` + feature-derived reasons, including graph-only candidates.
5. Agent stream shows `tool_call`/`tool_result` events live; every call is in `tool_calls`; a failing patch error flows back and the model retries.
6. Citation insert produces `\cite{key}` + a compilable `references.bib` entry (hostile titles included).
7. Compile → PDF, network-free (pre-warmed Tectonic).
8. MCP Inspector lists ten tools; `retrieve_evidence` works from Claude Desktop against the same graph.
9. `make test-backend` passes with zero external API calls.
