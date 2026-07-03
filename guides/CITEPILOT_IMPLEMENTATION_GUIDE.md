# CitePilot — Implementation Guide (v2, revised)

**Project:** CitePilot
**Concept:** An Overleaf + Cursor-style research workspace: browser LaTeX editor on the left, an agentic GraphRAG research assistant on the right, backed by a scientific knowledge graph.
**This document is the single source of truth for implementation.** It supersedes any earlier blueprint. All design fixes are already merged in.

---

## 0. Instructions for the Coding Agent

You are implementing CitePilot exactly according to this guide. Follow these rules:

1. **Work milestone by milestone** (Section 20). Do not begin a milestone until the previous milestone's acceptance criteria pass.
2. **Every milestone ends with you running the app** (`docker compose up`), verifying endpoints manually or via tests, and confirming acceptance criteria.
3. **Never hardcode secrets.** All secrets and configuration come from environment variables via `pydantic-settings`.
4. **Never call external APIs (OpenAlex, Crossref, Semantic Scholar, LLM providers) in tests.** Use the JSON fixtures under `backend/app/tests/fixtures/`.
5. **Keep layers separate.** The graph layer, vector layer, LLM layer, ingestion layer, agent layer, and MCP layer are separate Python packages with no circular imports. MCP tools and API agent tools are thin wrappers around one shared core implementation (`app/agent/tools.py`).
6. **Log every meaningful event** (Section 18) with structured JSON logs.
7. **Prefer small, typed, observable steps.** Every tool the agent can call is a plain async Python function with Pydantic input/output models.
8. **The backend is fully async.** Use `async def` everywhere, asyncpg, httpx.AsyncClient, the async Neo4j driver, and **arq** (not RQ, not Celery) for background jobs.
9. **The frontend should be implemented completely and autonomously by you.** The human developer will hand-write the backend to learn from it, but will not modify the frontend. Frontend code must therefore be clean, conventional, and self-contained — no clever abstractions that require reading your mind.
10. **Where this guide gives exact SQL, Cypher, schemas, or JSON contracts, implement them verbatim.** Where it gives shapes or sketches, match the shape and fill in idiomatic details.

Build order (do not deviate):

```text
runnable app → durable project files → paper ingestion → graph sync
→ vector retrieval → hybrid (RRF) retrieval → agent tool loop
→ citation insertion → LaTeX compilation → MCP server → polish
```

Do not start with the agent. Do not start with a fancy UI. Do not build authentication beyond a seeded dev user. Do not build PDF full-text parsing — metadata and abstracts only for MVP.

---

## 1. Product Vision and MVP Scope

CitePilot lets a researcher write LaTeX while an AI agent reasons over a citation-aware scientific knowledge graph. The core thesis:

> Researchers don't just need semantically similar text chunks. They need **relationship-aware retrieval**: which papers cite, are cited by, share references with, are co-cited alongside, and share concepts with the papers relevant to what they're writing.

### 1.1 MVP user flow (build exactly this)

1. User creates a project → gets `main.tex` + `references.bib`.
2. User edits LaTeX in a browser editor (CodeMirror).
3. User searches OpenAlex for a paper and imports it.
4. Backend stores metadata in Postgres, mirrors nodes/edges to Neo4j (including **stub papers** for all references), embeds title+abstract into pgvector.
5. User selects a paragraph and asks the agent: "What related work should I cite here?"
6. Agent runs a tool loop: inspects the project, runs hybrid retrieval (vector + graph, fused with RRF), ranks candidates, streams back suggestions with human-readable *reasons*.
7. User clicks "Insert citation" → `\cite{key}` at cursor, BibTeX appended to `references.bib`.
8. User compiles with Tectonic and sees the PDF preview.
9. The same tools are exposed through an MCP server usable from Claude Desktop / MCP Inspector.

### 1.2 Explicitly out of scope for MVP

Real-time collaboration, multi-user permissions, full PDF parsing (GROBID), fine-tuned local models, Kubernetes, full citation style formatting, payments, the research-gap engine (`find_research_gaps` is a documented future tool, **not** an MVP tool), and force-directed graph layouts.

---

## 2. Technology Stack (final decisions)

### 2.1 Frontend (agent-owned; see Section 16)

- **Vite + React + TypeScript**, **Tailwind CSS**, **shadcn/ui**.
- **CodeMirror 6** via `@uiw/react-codemirror` for the LaTeX editor.
- **TanStack Query** for server state; **Zustand** for editor/agent UI state; **Zod** for API schema parsing; **React Hook Form** where forms exist.
- **@xyflow/react** for the citation graph panel (radial layout; force-directed is future work).
- Agent streaming consumed with **`fetch()` + ReadableStream** (see 14.6). Never use `EventSource` — it cannot send POST bodies.

### 2.2 Backend

- **Python 3.12**, **FastAPI**, **Uvicorn**.
- **Pydantic v2** + **pydantic-settings**.
- **SQLAlchemy 2.0 (async)** + **Alembic** + **asyncpg**.
- **neo4j** official async Python driver.
- **httpx** (AsyncClient) + **tenacity** for retries.
- **arq** for background jobs (async-native, Redis-backed). *Not RQ* — RQ is sync-only and fights the async stack; arq jobs are plain `async def` functions.
- **structlog** with JSON rendering.
- **pytest + pytest-asyncio**, **ruff** (lint + format), **mypy** in CI if time allows.

### 2.3 Storage

- **Postgres 16** with **pgvector** — durable app state + vector search.
- **Neo4j 5 Community** — graph traversal (citation neighborhoods, co-citation, bibliographic coupling, concept overlap).
- **Redis 7** — arq queue backend + external-API response cache.

Division of responsibility: Postgres is the **source of truth** for all entities. Neo4j holds **graph-optimized mirrors** of papers/authors/concepts and relationships; if Neo4j were wiped, it must be fully rebuildable from Postgres (implement `resync_graph` as an idempotent function).

### 2.4 LLM / Embeddings

Provider-agnostic adapter layer. One cloud provider wired via env for MVP; a `FakeLLMClient` and `FakeEmbeddingClient` for all tests.

```python
class LLMClient(Protocol):
    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse: ...

class EmbeddingClient(Protocol):
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

**Embedding dimension rule:** the pgvector column dimension is fixed at migration time and MUST equal `EMBEDDING_DIM`. Add a startup assertion that compares `settings.EMBEDDING_DIM` to the actual column typmod (query `information_schema` / `pg_attribute`) and fails loudly on mismatch. Note: pgvector HNSW supports ≤ 2000 dimensions; the default is 1536. Store `embedding_model` in each chunk's `metadata` JSON so mixed-model corpora are detectable.

### 2.5 LaTeX

- **Tectonic** compiled in the worker container.
- **Pre-warm the Tectonic bundle at image build time** (Section 15.2) so first compile is fast and the runtime compile can be network-restricted.

### 2.6 MCP

- **Official MCP Python SDK (FastMCP)**, **stdio transport** for MVP. Streamable HTTP is future work and requires auth before exposure (Section 19.4).

---

## 3. Repository Structure

Monorepo:

```text
citepilot/
  README.md
  docker-compose.yml
  .env.example
  .gitignore
  Makefile

  apps/
    web/
      package.json            # "dev": "vite --host 0.0.0.0 --port 3000"
      vite.config.ts
      tsconfig.json
      index.html
      src/
        main.tsx
        App.tsx               # route shell / project list
        pages/
          ProjectListPage.tsx
          WorkspacePage.tsx
      components/
        editor/  LatexEditor.tsx  FileTree.tsx  PdfPreview.tsx
        agent/   AgentPanel.tsx  ToolTrace.tsx  CitationSuggestionCard.tsx  PatchReviewCard.tsx
        graph/   CitationGraph.tsx
        papers/  PaperSearchDialog.tsx  ProjectPaperList.tsx
        ui/      ...shadcn components...
      lib/
        api.ts                # typed fetch wrapper
        schemas.ts            # zod schemas mirroring backend contracts
        stream.ts             # fetch + ReadableStream SSE parser (14.6)
        queryClient.ts
      stores/
        editorStore.ts  agentStore.ts

  backend/
    pyproject.toml
    alembic.ini
    alembic/
      env.py
      versions/
    app/
      main.py                 # FastAPI app factory, CORS, lifespan
      config.py               # pydantic-settings Settings
      logging.py              # structlog config
      deps.py                 # FastAPI dependencies (db session, clients)

      api/
        router.py
        routes/
          health.py  projects.py  files.py  papers.py
          jobs.py    graph.py     agent.py  latex.py

      db/
        postgres.py           # engine/session factory
        models.py             # SQLAlchemy models

      graph/
        neo4j_client.py       # driver lifecycle
        schema.py             # constraint bootstrap
        queries.py            # all Cypher lives here, parameterized
        sync.py               # Postgres -> Neo4j mirroring, resync_graph()

      retrieval/
        chunking.py
        embeddings.py         # EmbeddingClient impls + Fake
        vector_search.py
        graph_search.py
        fusion.py             # Reciprocal Rank Fusion
        hybrid.py             # HybridRetriever orchestration
        explain.py            # feature -> reason strings

      ingestion/
        openalex.py           # client with polite pool + Redis cache
        crossref.py           # BibTeX via content negotiation
        semantic_scholar.py   # optional, no-ops without API key
        normalize.py          # DTOs, DOI normalization, dedup
        bibtex.py             # fallback generation + LaTeX escaping
        upsert.py             # dedup-aware Postgres upsert + stub creation

      latex/
        compiler.py           # tectonic subprocess, timeout, artifact handling
        patcher.py            # anchor-based patch application
        sanitizer.py          # path safety

      agent/
        orchestrator.py       # the tool loop + streaming
        tool_registry.py      # name -> (fn, input model, output model, description)
        tools.py              # core tool implementations (single source)
        prompts.py
        schemas.py            # Pydantic models for all tool I/O
        llm/
          base.py  providers.py  openai_client.py  anthropic_client.py  fake.py

      mcp_server/
        server.py             # FastMCP entrypoint (stdio)
        tools.py              # thin wrappers over app.agent.tools

      workers/
        arq_app.py            # WorkerSettings, redis settings
        jobs.py               # ingest_paper, expand_citation_graph, embed_chunks, compile_latex

      tests/
        conftest.py
        test_health.py
        test_normalize.py           # DOI normalization, abstract reconstruction, dedup matching
        test_bibtex.py              # key generation, LaTeX escaping (hostile-title fixture)
        test_fusion.py              # RRF math
        test_hybrid_retrieval.py    # fake embeddings + fake graph
        test_latex_patcher.py       # anchor patches: 0 matches, 1 match, 2 matches
        test_path_sanitizer.py
        test_agent_stream.py        # SSE event sequence with FakeLLMClient
        fixtures/
          openalex_work.json  openalex_search.json
          crossref_bibtex.txt semantic_scholar_paper.json

  infra/
    docker/
      backend.Dockerfile  web.Dockerfile  worker.Dockerfile
    scripts/
      init_neo4j.cypher
```

Note: there is **no** `init_postgres.sql`. The `vector` extension is created inside the first Alembic migration (`CREATE EXTENSION IF NOT EXISTS vector;`) so it works on fresh *and* existing volumes.

---

## 4. Environment Variables

`.env.example`:

```env
# App
APP_ENV=development
APP_NAME=CitePilot
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000

# Postgres
DATABASE_URL=postgresql+asyncpg://citepilot:citepilot@postgres:5432/citepilot
POSTGRES_DB=citepilot
POSTGRES_USER=citepilot
POSTGRES_PASSWORD=citepilot

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=citepilot-password

# Redis
REDIS_URL=redis://redis:6379/0

# External scholarly APIs
OPENALEX_MAILTO=your_email@example.com   # REQUIRED: client refuses to start without it
SEMANTIC_SCHOLAR_API_KEY=                # optional; S2 client no-ops when empty
CROSSREF_MAILTO=your_email@example.com

# LLM
LLM_PROVIDER=anthropic
LLM_MODEL=
LLM_API_KEY=

# Embeddings
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=
EMBEDDING_DIM=1536                       # MUST match paper_chunks.embedding column dim

# LaTeX
LATEX_WORKDIR=/tmp/citepilot-latex
LATEX_COMPILE_TIMEOUT_SECONDS=30

# Dev auth
DEV_USER_ID=00000000-0000-0000-0000-000000000001
```

---

## 5. Docker Compose

`docker-compose.yml` — healthchecks are mandatory; `depends_on` gates on `service_healthy` so cold starts are deterministic:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: citepilot-postgres
    environment:
      POSTGRES_DB: citepilot
      POSTGRES_USER: citepilot
      POSTGRES_PASSWORD: citepilot
    ports: ["5432:5432"]
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U citepilot"]
      interval: 5s
      timeout: 3s
      retries: 10

  neo4j:
    image: neo4j:5-community
    container_name: citepilot-neo4j
    environment:
      NEO4J_AUTH: neo4j/citepilot-password
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_server_memory_heap_max__size: 1G
      NEO4J_server_memory_pagecache_size: 512M
    ports: ["7474:7474", "7687:7687"]
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12

  redis:
    image: redis:7
    container_name: citepilot-redis
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  backend:
    build: { context: ., dockerfile: infra/docker/backend.Dockerfile }
    container_name: citepilot-backend
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      neo4j:    { condition: service_healthy }
      redis:    { condition: service_healthy }
    ports: ["8000:8000"]
    volumes:
      - ./backend:/app/backend
      - latex_artifacts:/tmp/citepilot-latex
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build: { context: ., dockerfile: infra/docker/worker.Dockerfile }
    container_name: citepilot-worker
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      neo4j:    { condition: service_healthy }
      redis:    { condition: service_healthy }
    volumes:
      - ./backend:/app/backend
      - latex_artifacts:/tmp/citepilot-latex
    command: arq app.workers.arq_app.WorkerSettings

  web:
    build: { context: ., dockerfile: infra/docker/web.Dockerfile }
    container_name: citepilot-web
    env_file: .env
    depends_on: [backend]
    ports: ["3000:3000"]
    volumes:
      - ./apps/web:/app/apps/web
      - /app/apps/web/node_modules
    command: pnpm dev            # package.json dev script: "vite --host 0.0.0.0 --port 3000"

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  latex_artifacts:
```

Makefile targets: `up`, `down`, `logs`, `backend-shell`, `web-shell`, `migrate` (alembic upgrade head inside backend container), `test-backend` (pytest inside backend container), `resync-graph` (runs the graph rebuild script).

---

## 6. Postgres Schema

All tables created via Alembic. First migration begins with `CREATE EXTENSION IF NOT EXISTS vector;`.

### 6.1 users, projects, files

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE,
  display_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seed one dev user with id = DEV_USER_ID on startup (idempotent).

CREATE TABLE projects (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project_files (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  content TEXT NOT NULL,
  version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(project_id, path)
);

CREATE TABLE file_versions (
  id UUID PRIMARY KEY,
  file_id UUID NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
  version INT NOT NULL,
  content TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'user',   -- 'user' | 'agent'
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(file_id, version)
);
```

**Versioning policy (implement exactly):** debounced autosave updates `project_files.content` in place *without* bumping `version` and *without* writing `file_versions`. A `file_versions` snapshot + version bump happens only on (a) explicit save (Cmd+S / Save button — frontend sends `explicit: true`), and (b) every agent-applied patch (`created_by = 'agent'`). Agent patches always snapshot: that is the undo story for AI edits.

### 6.2 papers (with stub support), authors, citations, concepts

```sql
CREATE TABLE papers (
  id UUID PRIMARY KEY,
  openalex_id TEXT UNIQUE,
  semantic_scholar_id TEXT UNIQUE,
  doi TEXT UNIQUE,                 -- ALWAYS normalized before insert (Section 8.2)
  title TEXT,                      -- nullable: stubs may not have a title yet
  abstract TEXT,
  publication_year INT,
  publication_date DATE,
  venue_name TEXT,
  source_name TEXT,
  cited_by_count INT DEFAULT 0,
  url TEXT,
  pdf_url TEXT,
  is_stub BOOLEAN NOT NULL DEFAULT false,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE authors (
  id UUID PRIMARY KEY,
  openalex_id TEXT UNIQUE,
  semantic_scholar_id TEXT UNIQUE,
  name TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE paper_authors (
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
  author_order INT,
  PRIMARY KEY (paper_id, author_id)
);

CREATE TABLE citations (
  citing_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  cited_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'openalex',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (citing_paper_id, cited_paper_id)
);
CREATE INDEX citations_cited_idx ON citations (cited_paper_id);  -- reverse lookups

CREATE TABLE concepts (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL DEFAULT 'concept',  -- concept|method|dataset|task|metric|field
  metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE paper_concepts (
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  score FLOAT,
  source TEXT NOT NULL DEFAULT 'openalex',
  PRIMARY KEY (paper_id, concept_id)
);
```

**Stub papers — the rule that makes the graph work:** when a paper is imported, every entry in its `referenced_works` is upserted as a stub (`is_stub = true`, `openalex_id` set, `title` null) and citation edges are inserted immediately. Without stubs there are no citation edges, and co-citation / bibliographic coupling return nothing. If a stub is later fully imported, the same row is enriched in place and `is_stub` flips to false — the UUID and every edge survive. Stubs are mirrored to Neo4j with an `is_stub` property so the UI can render them dimmed.

### 6.3 chunks + vector index

```sql
CREATE TABLE paper_chunks (
  id UUID PRIMARY KEY,
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  section TEXT,                    -- 'title_abstract' for MVP
  text TEXT NOT NULL,
  token_count INT,
  embedding vector(1536),
  metadata JSONB NOT NULL DEFAULT '{}',   -- includes embedding_model
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(paper_id, chunk_index)
);

CREATE INDEX paper_chunks_embedding_hnsw_idx
  ON paper_chunks USING hnsw (embedding vector_cosine_ops);
```

### 6.4 project papers, agent tables, jobs, compilations

```sql
CREATE TABLE project_papers (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  bibtex_key TEXT NOT NULL,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, paper_id),
  UNIQUE(project_id, bibtex_key)
);

CREATE TABLE agent_sessions (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  title TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_messages (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,              -- 'user' | 'assistant' | 'tool'
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_messages_session_idx ON agent_messages (session_id, created_at);

CREATE TABLE tool_calls (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL DEFAULT '{}',
  result JSONB,                    -- TRUNCATED to <= 4 KB with {"truncated": true} flag
  status TEXT NOT NULL DEFAULT 'pending',  -- pending|completed|failed
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',   -- queued|running|completed|failed
  queue_job_id TEXT,                       -- arq job id linkage
  input JSONB NOT NULL DEFAULT '{}',
  result JSONB,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE latex_compilations (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued',
  main_file_path TEXT NOT NULL DEFAULT 'main.tex',
  pdf_path TEXT,
  logs TEXT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
```

**Job state convention:** the `jobs` table is the source of truth for the UI. The API creates the row (`queued`), enqueues the arq job, stores the arq job id in `queue_job_id`. The worker updates the row to `running` at start and `completed`/`failed` at end. The arq registry is an implementation detail; the frontend never talks to it.

---

## 7. Neo4j Graph Schema

### 7.1 Nodes

```text
(:Paper   {id, openalex_id, doi, title, year, cited_by_count, is_stub})
(:Author  {id, openalex_id, name})
(:Venue   {id, name})
(:Concept {id, name})
(:Method  {id, name})     -- future: LLM extraction
(:Dataset {id, name})     -- future
(:Task    {id, name})     -- future
```

`id` is always the Postgres UUID (string). Neo4j is a rebuildable mirror.

### 7.2 Relationships

```text
(:Paper)-[:CITES]->(:Paper)
(:Paper)-[:WRITTEN_BY {author_order}]->(:Author)
(:Paper)-[:PUBLISHED_IN]->(:Venue)
(:Paper)-[:MENTIONS_CONCEPT {score, source}]->(:Concept)
(:Paper)-[:USES_METHOD {confidence, source}]->(:Method)        -- future
(:Paper)-[:EVALUATES_ON {confidence, source}]->(:Dataset)      -- future
```

### 7.3 Constraints (`infra/scripts/init_neo4j.cypher`, applied idempotently at backend startup)

```cypher
CREATE CONSTRAINT paper_id_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE;

CREATE CONSTRAINT author_id_unique IF NOT EXISTS
FOR (a:Author) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT concept_name_unique IF NOT EXISTS
FOR (c:Concept) REQUIRE c.name IS UNIQUE;

CREATE INDEX paper_year_index IF NOT EXISTS FOR (p:Paper) ON (p.year);
CREATE INDEX paper_stub_index IF NOT EXISTS FOR (p:Paper) ON (p.is_stub);
```

### 7.4 Core Cypher queries (`graph/queries.py`, all parameterized)

**Never use the undirected variable-length pattern `-[:CITES*1..2]-` with a bare LIMIT** — on a hub node (a survey cited 10k times) it explodes, and LIMIT truncates arbitrarily. Expand per direction with a per-hop cap instead.

References of seed (what it cites):

```cypher
MATCH (seed:Paper {id: $paper_id})-[:CITES]->(cited:Paper)
RETURN cited
ORDER BY cited.cited_by_count DESC
LIMIT $limit;
```

Citers of seed:

```cypher
MATCH (citing:Paper)-[:CITES]->(seed:Paper {id: $paper_id})
RETURN citing
ORDER BY citing.cited_by_count DESC
LIMIT $limit;
```

Two-hop neighborhood, capped per hop (used by the graph panel):

```cypher
MATCH (seed:Paper {id: $paper_id})
CALL {
  WITH seed
  MATCH (seed)-[:CITES]->(n1:Paper)
  RETURN n1 AS hop1 ORDER BY n1.cited_by_count DESC LIMIT $per_hop
  UNION
  WITH seed
  MATCH (n1:Paper)-[:CITES]->(seed)
  RETURN n1 AS hop1 ORDER BY n1.cited_by_count DESC LIMIT $per_hop
}
WITH seed, collect(DISTINCT hop1) AS hop1s
UNWIND hop1s AS h
OPTIONAL MATCH (h)-[r:CITES]-(m:Paper)
WHERE m = seed OR m IN hop1s
RETURN seed, hop1s, collect(DISTINCT r) AS rels;
```

Bibliographic coupling (shares references with seed):

```cypher
MATCH (seed:Paper {id: $paper_id})-[:CITES]->(ref:Paper)<-[:CITES]-(other:Paper)
WHERE other.id <> seed.id
RETURN other.id AS paper_id, count(ref) AS shared_references
ORDER BY shared_references DESC, other.cited_by_count DESC
LIMIT $limit;
```

Co-citation (cited together with seed):

```cypher
MATCH (citing:Paper)-[:CITES]->(seed:Paper {id: $paper_id})
MATCH (citing)-[:CITES]->(other:Paper)
WHERE other.id <> seed.id
RETURN other.id AS paper_id, count(citing) AS co_citation_count
ORDER BY co_citation_count DESC, other.cited_by_count DESC
LIMIT $limit;
```

Shared concepts:

```cypher
MATCH (seed:Paper {id: $paper_id})-[:MENTIONS_CONCEPT]->(c:Concept)<-[:MENTIONS_CONCEPT]-(other:Paper)
WHERE other.id <> seed.id
RETURN other.id AS paper_id, collect(c.name) AS shared_concepts, count(c) AS concept_overlap
ORDER BY concept_overlap DESC, other.cited_by_count DESC
LIMIT $limit;
```

### 7.5 Sync (`graph/sync.py`)

- `sync_paper(paper_id)` — MERGE the Paper node + author/venue/concept nodes + edges, using `MERGE ... ON CREATE SET ... ON MATCH SET ...` so re-imports are idempotent.
- `sync_citations(citing_id, cited_ids)` — batch MERGE of `:CITES` edges (UNWIND a parameter list, one round trip).
- `resync_graph()` — wipe and rebuild all of Neo4j from Postgres. Must be runnable via `make resync-graph`. This proves Neo4j is a derived store.

---

## 8. Paper Ingestion

### 8.1 Flow

```text
POST /api/papers/search  -> API calls OpenAlex (through Redis cache) -> results to UI
POST /api/papers/import  -> API creates jobs row -> enqueues arq ingest_paper -> returns job_id
worker ingest_paper:
  1. Fetch full work from OpenAlex (cached).
  2. Normalize into NormalizedPaper DTO.
  3. Dedup-aware upsert into Postgres (8.3).
  4. Upsert all referenced_works as STUB papers; insert citation edges.
  5. Mirror paper + stubs + edges to Neo4j (graph/sync.py).
  6. Build the single title+abstract chunk; enqueue embed_chunks (or inline).
  7. Link paper to project (project_papers) with a generated bibtex_key.
  8. Mark jobs row completed.
```

### 8.2 Normalization rules (`ingestion/normalize.py`)

**DOI normalization (apply before ANY read or write of a DOI):**

```python
def normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    doi = raw.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return doi.lower() or None
```

DOIs are case-insensitive by spec and arrive with/without the `https://doi.org/` prefix; the UNIQUE constraint is meaningless without this.

**OpenAlex abstract reconstruction** (abstracts arrive as an inverted index):

```python
def reconstruct_openalex_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    positions = [(i, word) for word, idxs in inv.items() for i in idxs]
    return " ".join(word for _, word in sorted(positions))
```

**Normalized DTO — every source converges here before touching storage:**

```python
class NormalizedAuthor(BaseModel):
    source_id: str | None = None
    name: str
    order: int | None = None

class NormalizedConcept(BaseModel):
    name: str
    type: str = "concept"
    score: float | None = None
    source: str

class NormalizedPaper(BaseModel):
    source: str                       # 'openalex' | 'semantic_scholar' | 'crossref'
    source_id: str
    title: str | None
    doi: str | None                   # already normalized
    abstract: str | None
    publication_year: int | None
    publication_date: str | None
    venue_name: str | None
    cited_by_count: int | None
    url: str | None
    pdf_url: str | None
    authors: list[NormalizedAuthor] = []
    concepts: list[NormalizedConcept] = []
    reference_source_ids: list[str] = []   # openalex ids of referenced works
    raw: dict = {}
```

OpenAlex field mapping: `id -> openalex_id`, `doi -> doi (normalized)`, `abstract_inverted_index -> abstract`, `primary_location.source.display_name -> venue_name`, `referenced_works -> reference_source_ids`, `authorships -> authors`, `concepts/topics -> concepts`, `open_access.oa_url -> pdf_url`.

### 8.3 Dedup-aware upsert (`ingestion/upsert.py`)

Match order on import (first hit wins):

1. normalized DOI
2. `openalex_id`
3. `semantic_scholar_id`
4. last resort: normalized title (lowercase, alphanumeric-only, collapsed whitespace) + `publication_year`

On match: **enrich the existing row** — fill nulls, update `cited_by_count`, merge `metadata`, set `is_stub = false` if it was a stub. Never insert a duplicate. On no match: insert. This guarantees a paper imported via two sources keeps one UUID, so its citation edges never split.

### 8.4 Stub creation

For each `reference_source_ids` entry: upsert `(openalex_id=ref_id, is_stub=true)` — a bare row, title null. Insert `citations (citing, cited)` edges. Batch this: one `INSERT ... ON CONFLICT DO NOTHING` for stubs, one for edges.

`expand_citation_graph_job(project_id, top_n=10)`: find the most-referenced stubs within the project's citation neighborhood and promote them to full papers (fetch metadata, enrich in place, sync graph). Exposed to the user as an "Enrich graph" button — this is a great demo moment (the graph visibly densifies).

### 8.5 External API clients — rate limits and caching

- **OpenAlex** (`ingestion/openalex.py`): always send `mailto={OPENALEX_MAILTO}` (polite pool, ~10 req/s). The client raises at startup if `OPENALEX_MAILTO` is unset. tenacity retry: 3 attempts, exponential backoff, retry on 429/5xx.
- **Crossref** (`ingestion/crossref.py`): used only for BibTeX content negotiation (Section 12.2). Send `mailto` in the User-Agent.
- **Semantic Scholar** (`ingestion/semantic_scholar.py`): the anonymous public pool is shared and tiny (~100 req/5 min across all users) — never rely on it. The client is a clean no-op when `SEMANTIC_SCHOLAR_API_KEY` is empty; with a key it enriches papers (fields of study, tldr).
- **Redis cache** wrapping every external GET: key `ext:{source}:{endpoint}:{sha1(normalized-params)}`, TTL 24h for searches, 7 days for work detail fetches. Repeated demos become instant and rate limits stop mattering in dev.

---

## 9. Chunking and Embeddings

### 9.1 MVP chunking: one chunk per paper

```text
chunk_index 0, section 'title_abstract':
  "{title}\n\n{abstract}"
```

**Do not create synthetic chunks** (concept summaries, citation metadata summaries). Template-generated text is lexically similar to *other template text*, not to real queries — it pollutes top-k results. Concept overlap is already a graph signal (7.4); encoding it in vector space double-counts it in the fusion step. Full-text chunking arrives with PDF parsing, post-MVP; the schema (`chunk_index`, `section`) is already ready for it.

### 9.2 Embedding write path

`embed_chunks(paper_id)`: read chunks with null embeddings, call `EmbeddingClient.embed_texts` in batches of ≤ 64, write vectors, stamp `metadata.embedding_model`. Skip papers with no abstract (title-only chunks are still embedded — a title is a fine retrieval key).

### 9.3 Vector search (`retrieval/vector_search.py`)

Search is **global across all imported papers**, not project-scoped — discovering papers the user hasn't imported yet is the product's point. Project membership is surfaced in results (`in_project` flag) and used as a light fusion signal, never as a filter.

```sql
SELECT pc.id, pc.paper_id, pc.text, pc.section,
       p.title, p.publication_year, p.cited_by_count, p.is_stub,
       1 - (pc.embedding <=> :query_embedding) AS similarity
FROM paper_chunks pc
JOIN papers p ON p.id = pc.paper_id
WHERE pc.embedding IS NOT NULL
ORDER BY pc.embedding <=> :query_embedding
LIMIT :limit;
```

---

## 10. Hybrid GraphRAG Retrieval

This is the technical heart of the project. Implement it exactly as specified.

### 10.1 Pipeline (`retrieval/hybrid.py`)

```python
class HybridRetriever:
    async def retrieve(
        self,
        project_id: UUID,
        query: str,
        seed_paper_ids: list[UUID] | None = None,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        # 1. Embed the query.
        qvec = (await self.embeddings.embed_texts([query]))[0]

        # 2. Vector list: top 30 chunks -> deduped ranked paper list.
        vector_list = await self.vector_store.search(qvec, limit=30)

        # 3. Seeds: explicit seeds, else top 5 distinct papers from vector list.
        seeds = seed_paper_ids or top_distinct_papers(vector_list, n=5)

        # 4. Graph lists (one ranked list per signal, per 7.4 queries):
        coupling_list   = await self.graph.bibliographic_coupling(seeds, limit=20)
        cocitation_list = await self.graph.co_citation(seeds, limit=20)
        concepts_list   = await self.graph.shared_concepts(seeds, limit=20)
        neighbors_list  = await self.graph.direct_neighbors(seeds, limit=20)

        # 5. Fuse with Reciprocal Rank Fusion (10.2).
        fused = rrf_fuse({
            "vector": vector_list,
            "coupling": coupling_list,
            "co_citation": cocitation_list,
            "shared_concepts": concepts_list,
            "citation_neighbors": neighbors_list,
        }, k=60)

        # 6. Attach features + explanation strings (10.3), fetch supporting chunks.
        return await self.hydrate(fused[:limit], project_id=project_id, query=query)
```

### 10.2 Reciprocal Rank Fusion (`retrieval/fusion.py`)

Do **not** implement a hand-tuned weighted sum of raw scores — cosine similarities, citation counts, and path distances live on incompatible scales and the weights become an untestable guessing game. RRF is scale-free, parameter-light, and the standard answer for hybrid retrieval:

```python
def rrf_fuse(ranked_lists: dict[str, list[UUID]], k: int = 60) -> list[FusedCandidate]:
    scores: dict[UUID, float] = defaultdict(float)
    sources: dict[UUID, list[str]] = defaultdict(list)
    for source_name, papers in ranked_lists.items():
        for rank, paper_id in enumerate(papers, start=1):
            scores[paper_id] += 1.0 / (k + rank)
            sources[paper_id].append(source_name)
    return sorted(
        (FusedCandidate(paper_id=p, score=s, retrieval_sources=sources[p])
         for p, s in scores.items()),
        key=lambda c: c.score, reverse=True,
    )
```

A paper appearing in multiple lists (semantically similar AND co-cited AND concept-overlapping) naturally rises — which is precisely the GraphRAG thesis expressed in three lines. Unit test `test_fusion.py`: multi-list membership beats single-list top rank; empty lists are handled; determinism.

### 10.3 Features and explanations (`retrieval/explain.py`)

For each final candidate, compute features **for explanation, not for scoring**:

```text
retrieval_sources (from fusion), shared_reference_count, co_citation_count,
shared_concept_names, min_graph_distance, cited_by_count, publication_year,
in_project (bool), is_stub (bool)
```

Render a reason string from features, e.g.:

> "One citation hop from Lewis et al. 2020, co-cited with it by 7 papers, shares concepts {retrieval-augmented generation, knowledge graphs}, and is semantically close to your paragraph."

Never return a bare score. The reason strings are what make the demo (and the interview story) land.

### 10.4 Stub handling in results

Stubs can appear in graph lists (they have edges but no abstract). Keep them in results, flagged `is_stub: true` — the UI renders an "Import full paper" action instead of "Insert citation". A recommendation the user can act on by importing is a feature, not a bug.

---

## 11. Agent Architecture

### 11.1 Philosophy

The agent is a **tool loop, not a magic box**. Every step is a typed tool call, logged to `tool_calls`, and streamed to the UI as a trace event. No hidden chain-of-thought is shown — only concise tool-trace summaries.

**There is no separate intent classifier.** The tool-calling model routes implicitly: given well-described tools, it selects `retrieve_evidence` for citation questions and `patch_latex_file` for edits on its own. An explicit classifier adds an LLM round-trip of latency and a new failure mode (misrouted intent) for zero benefit at this scale. An `intent` label may be *emitted* by the model in its first response for logging/analytics only — it must never gate control flow.

### 11.2 The tool loop (`agent/orchestrator.py`)

```python
async def run_agent_turn(session, user_message, context, emit) -> None:
    """emit(event_name, payload) pushes an SSE event to the client."""
    messages = build_messages(session, user_message, context)   # includes system prompt
    for _ in range(MAX_TOOL_ITERATIONS):                        # MAX = 8
        response = await llm.complete(messages, tools=tool_registry.specs())

        for text_delta in response.text_stream:
            await emit("message_delta", {"text": text_delta})

        if not response.tool_calls:
            break

        for call in response.tool_calls:
            await emit("tool_call", {"tool_name": call.name, "arguments": call.arguments})
            record = await log_tool_call_start(session, call)
            try:
                result = await tool_registry.execute(call.name, call.arguments)
                await log_tool_call_end(record, result)          # truncate stored result to 4 KB
                await emit("tool_result", {"tool_name": call.name, "summary": result.summary})
            except ToolError as e:
                await log_tool_call_error(record, e)
                await emit("tool_result", {"tool_name": call.name, "error": str(e)})
                result = e.as_tool_result()                      # agent sees the error and can retry
            messages.append(tool_result_message(call, result))

    await persist_messages(session, messages)
    await emit("done", {"session_id": str(session.id)})
```

Key properties: bounded iterations; every tool result (including errors) goes back into the conversation so the model can self-correct; every call is persisted; everything the model does is visible in the UI trace.

### 11.3 Tool registry (`agent/tool_registry.py`)

A tool is registered once with: name, description (the model reads this — write it carefully), Pydantic input model, Pydantic output model, and the async implementation from `agent/tools.py`. The registry generates provider tool specs (JSON schema) from the Pydantic models. Both the web agent and the MCP server consume this same registry — **tool logic exists in exactly one place**.

### 11.4 Context assembly

Each turn's user message is wrapped with project context:

```text
Project: {project_name}
Active file: {active_file_path}
Selected text:
{selected_text}

User request:
{message}
```

System prompt (`agent/prompts.py`):

```text
You are CitePilot, a research-writing assistant. You help users write LaTeX
research papers using retrieved scholarly evidence.

Rules:
- Use only evidence returned by tools for factual claims about papers.
- Never invent citations or BibTeX keys. Only use keys returned by tools.
- When recommending citations, explain why each paper is relevant.
- Distinguish foundational papers, recent papers, and directly related papers.
- If retrieved evidence is weak or empty, say so plainly.
- When editing LaTeX, preserve the user's style; change only what was asked.
- Prefer concise responses.
```

---

## 12. Agent Tools (canonical specs)

All tools live in `agent/tools.py` with Pydantic I/O in `agent/schemas.py`. Every project-scoped tool takes `project_id` and verifies it exists (real access control is future work, but the signature is ready). MVP tool list:

```text
search_papers, import_paper, get_paper, get_citation_neighborhood,
retrieve_evidence, rank_related_work, suggest_bibtex,
inspect_latex_project, patch_latex_file, compile_latex
```

(`find_research_gaps`, `compare_papers`, `explain_citation_path` are future tools — do not implement.)

### 12.1 Retrieval tools

**search_papers** — input `{query, source: "local"|"openalex", year_min?, year_max?, limit=10}`; output a list of `{paper_id|null, external_id, title, year, authors, abstract, cited_by_count, imported: bool}`. `local` searches Postgres (title ILIKE + optional vector search); `openalex` hits the cached client.

**import_paper** — input `{source, source_id, project_id}`; output `{job_id, status: "queued"}`. Enqueues the same ingest job as the API route.

**get_paper** — input `{paper_id}`; output the full paper row + authors + concepts + `in_project`.

**get_citation_neighborhood** — input `{paper_id, per_hop=15, include_shared_concepts=true}`; output `{nodes, edges, ranked_neighbors: [{paper_id, reason, signals}]}` using the capped queries from 7.4.

**retrieve_evidence** — input `{project_id, query, seed_paper_ids?, limit=10}`; runs the HybridRetriever (Section 10); output `{evidence: [{paper_id, title, chunk_id, text, score, retrieval_sources, reason, in_project, is_stub}]}`.

**rank_related_work** — input `{project_id, section_text, limit=8}`; a convenience composition: `retrieve_evidence` on the section text, then formats `{recommendations: [{paper_id, bibtex_key|null, title, reason, evidence_snippets, score, is_stub}]}`. `bibtex_key` is null unless the paper is already in the project.

### 12.2 BibTeX tools

**suggest_bibtex** — input `{paper_ids, project_id}`; output `{entries: [{paper_id, bibtex_key, bibtex}]}`.

BibTeX acquisition order:

1. **If the paper has a DOI: Crossref content negotiation.** `GET https://doi.org/{doi}` with header `Accept: application/x-bibtex`. Publisher entries have correct fields and capitalization protection. Cache the response.
2. **Fallback: hand-rolled generation** (`ingestion/bibtex.py`) from stored metadata. This path MUST escape LaTeX special characters in every field (`& % $ # _ { } ~ ^ \`) and brace-protect acronyms in titles (`{GraphRAG}`). An unescaped `&` in a title breaks compilation three steps away from the cause — `test_bibtex.py` includes a hostile-title fixture ("P&L of Q&A systems: 100% _better_").

Key format: `{firstauthorlastname}{year}{firsttitleword}`, lowercase, ASCII-folded (e.g., `lewis2020retrieval`). Collisions within a project append `a`, `b`, `c`. The generated key is rewritten if it collides with `project_papers.bibtex_key`.

### 12.3 LaTeX tools

**inspect_latex_project** — input `{project_id, paths?}`; output `{files: [{path, content, version}]}`. Paths pass through the sanitizer (15.4). If `paths` omitted, return all project files (MVP projects are small).

**patch_latex_file** — **anchor-based only.** Character offsets computed by an LLM are unreliable (models miscount, and wrong offsets corrupt silently). Anchored patches fail loudly and safely:

```python
class ReplaceTextPatch(BaseModel):
    operation: Literal["replace_text"]
    path: str
    base_version: int
    old_text: str          # must occur EXACTLY ONCE in the file
    new_text: str

class InsertAfterPatch(BaseModel):
    operation: Literal["insert_after"]
    path: str
    base_version: int
    anchor_text: str       # must occur EXACTLY ONCE
    new_text: str
```

Application rules (`latex/patcher.py`):
- If `base_version` != current version → structured error `stale_version`.
- If anchor occurs 0 times → error `anchor_not_found`; if >1 time → error `anchor_ambiguous` (include the count). Errors flow back into the tool loop so the model retries with a longer anchor.
- On success: apply, bump version, snapshot to `file_versions` with `created_by='agent'`, return `{status: "applied", new_version}`.
- The web UI flow: the agent *proposes* the patch (streamed as a `patch_proposal` event); the backend applies it only after the user accepts (a separate authenticated endpoint call). Over MCP (no human in the UI loop), the tool applies directly — versioning is the safety net.

`test_latex_patcher.py` covers: exact-once success, zero matches, two matches, stale version, multi-line anchors.

**compile_latex** — input `{project_id, main_file_path="main.tex"}`; output `{compilation_id, status: "queued"}`. Enqueues the compile job.

---

## 13. MCP Server

### 13.1 Entrypoint (`mcp_server/server.py`)

```python
from mcp.server.fastmcp import FastMCP
from app.mcp_server.tools import register_tools

mcp = FastMCP("citepilot")
register_tools(mcp)

if __name__ == "__main__":
    mcp.run()   # stdio transport
```

(Verify the import path against the installed SDK version; adjust if the SDK has moved modules.)

### 13.2 Tool registration — wrappers only, zero logic

```python
def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def search_papers(query: str, source: str = "openalex", limit: int = 10) -> dict:
        """Search scholarly papers locally or on OpenAlex. Returns titles, years,
        authors, abstracts, and whether each paper is already imported."""
        return (await core.search_papers(SearchPapersInput(
            query=query, source=source, limit=limit))).model_dump()

    @mcp.tool()
    async def get_citation_neighborhood(paper_id: str, per_hop: int = 15) -> dict:
        """Return the citation neighborhood (nodes, edges, ranked neighbors with
        reasons) around a paper in the local knowledge graph."""
        ...
```

Register all ten MVP tools this way. Docstrings are the tool descriptions MCP clients show — write them for a model reader.

### 13.3 MCP safety rules

- Every input validated by the same Pydantic models as the web agent.
- Every call logged to `tool_calls` (session_id null).
- Responses capped: never return more than ~50 items or full file contents beyond project files.
- No arbitrary SQL, no arbitrary Cypher, no shell, no filesystem access outside project files.
- **stdio only for MVP.** The server has full database access; the moment it is exposed over Streamable HTTP it requires authentication — this is written into Section 19.4 so future-you cannot forget.

### 13.4 Verification

Milestone 11 acceptance includes driving the server with **MCP Inspector** (`npx @modelcontextprotocol/inspector`) and from Claude Desktop: call `search_papers`, `get_citation_neighborhood`, `retrieve_evidence` end-to-end. Document the client config JSON in the README.

---

## 14. FastAPI API

### 14.1 Router layout

```text
GET  /api/health
POST /api/projects                    GET /api/projects
GET  /api/projects/{id}/files         PUT /api/projects/{id}/files/{file_id}
POST /api/papers/search               POST /api/papers/import
GET  /api/papers/{paper_id}           GET /api/projects/{id}/papers
GET  /api/jobs/{job_id}                                   # generic job polling
GET  /api/graph/neighborhood?paper_id=&per_hop=
POST /api/agent/sessions              GET /api/agent/sessions/{id}/messages
POST /api/agent/stream                                    # SSE-formatted streaming response
POST /api/agent/patches/{tool_call_id}/accept             # user accepts a proposed patch
POST /api/latex/compile
GET  /api/latex/compilations/{id}
GET  /api/latex/compilations/{id}/pdf                     # streams application/pdf
```

### 14.2 CORS — configure on day one

Vite on :3000 calling FastAPI on :8000 is cross-origin; without this the first browser fetch fails:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

The streaming endpoint must pass through the same middleware (it does by default; do not mount it outside the app).

### 14.3 File update contract

`PUT /files/{file_id}` body: `{content, base_version, explicit: bool}`. If `base_version` is stale → `409 Conflict` with `{current_version, current_content}` in the body. **Frontend 409 behavior (implement exactly):** replace the editor buffer with `current_content`, show a toast "File changed elsewhere — reloaded latest", and offer an "Restore my edits" action that re-applies the local buffer as new content. No merge UI.

### 14.4 Job polling

`GET /api/jobs/{job_id}` → `{id, job_type, status, result, error}`. Frontend polls with TanStack Query `refetchInterval: 1500` while status is non-terminal, then invalidates the project-papers query.

### 14.5 Agent streaming — server side

`POST /api/agent/stream` with `{project_id, session_id|null, message, active_file_path, selected_text}` returns `Content-Type: text/event-stream` from a `StreamingResponse`. Event sequence:

```text
event: message_delta      data: {"text": "..."}
event: tool_call          data: {"tool_name": "...", "arguments": {...}}
event: tool_result        data: {"tool_name": "...", "summary": "..."}   # or {"error": "..."}
event: citation_suggestions  data: {"recommendations": [...]}
event: patch_proposal     data: {"tool_call_id": "...", "patch": {...}, "preview": {"before": "...", "after": "..."}}
event: done               data: {"session_id": "..."}
```

### 14.6 Agent streaming — client side (critical)

**Never use `EventSource`** — it only supports GET with no body. Implement `lib/stream.ts` with `fetch()` + a `ReadableStream` reader that buffers text, splits on `\n\n`, and parses `event:` / `data:` lines into typed events. Wire an `AbortController` to a Stop button. (Alternatively use `@microsoft/fetch-event-source`, which adds retry handling — either is acceptable; pick one and commit.)

`test_agent_stream.py` (backend): with `FakeLLMClient` scripted to emit one tool call then a final answer, POST to the endpoint via httpx and assert the exact event sequence `message_delta* → tool_call → tool_result → message_delta* → done`.

---

## 15. LaTeX Compilation

### 15.1 Project bootstrap files

On project creation, create these two files (version 1):

`main.tex`:

```tex
\documentclass{article}
\usepackage{hyperref}
\usepackage{cite}

\title{Untitled Research Draft}
\author{}
\date{\today}

\begin{document}
\maketitle

\section{Introduction}
Start writing here.

\bibliographystyle{plain}
\bibliography{references}

\end{document}
```

`references.bib`: empty file.

### 15.2 Tectonic in the worker image — pre-warm the bundle

Tectonic downloads its package bundle over the network on first compile. Two consequences if unhandled: the first demo compile takes minutes, and a network-restricted compile sandbox fails outright. Therefore `worker.Dockerfile` bakes the cache at build time:

```dockerfile
# after installing tectonic
RUN printf '\\documentclass{article}\\usepackage{hyperref}\\usepackage{cite}\\begin{document}warmup\\bibliographystyle{plain}\\end{document}\n' > /tmp/warmup.tex \
 && tectonic /tmp/warmup.tex --outdir /tmp && rm -f /tmp/warmup.*
```

The warmup document uses the same preamble as the bootstrap `main.tex` so its packages are cached. Runtime compiles then need no network.

### 15.3 Compile job (`latex/compiler.py`, arq job `compile_latex`)

```python
async def compile_project(project_id: UUID, main_file_path: str, compilation_id: UUID) -> None:
    files = await load_project_files(project_id)
    workdir = make_temp_workdir(compilation_id)          # under LATEX_WORKDIR
    write_files_safely(workdir, files)                   # paths pass sanitizer (15.4)
    proc = await asyncio.create_subprocess_exec(
        "tectonic", main_file_path, "--outdir", str(workdir / "out"),
        cwd=workdir, stdout=PIPE, stderr=PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.LATEX_COMPILE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await mark_failed(compilation_id, "timeout")
        return
    # persist logs; on success move PDF to artifact path; update latex_compilations row
```

Rules: no shell escape (never pass `-Z shell-escape`); timeout enforced; output size capped (reject PDFs > 20 MB); logs always stored; temp dir removed after artifact extraction.

### 15.4 Path sanitizer (`latex/sanitizer.py`)

Reject: absolute paths, any `..` segment, backslashes, null bytes, paths not matching `^[A-Za-z0-9._/-]+$`, hidden files (leading dot segments). Applies to file CRUD, `inspect_latex_project`, patch paths, and compile file writing. Unit-tested with a hostile-path table.

### 15.5 PDF serving

`GET /api/latex/compilations/{id}/pdf` streams the artifact with `Content-Type: application/pdf` and `Content-Disposition: inline`. The frontend preview is an `<object>`/`<iframe>` pointed at this URL — it needs a real URL, not JSON.

---

## 16. Frontend Specification (agent-owned)

The human developer will not modify frontend code. Implement it fully, conventionally, and completely — every screen below, no placeholders left at the end.

### 16.1 Screens

1. **Project list** (`/`): grid of projects, create-project dialog (name, description).
2. **Workspace** (`/projects/[projectId]`): three-pane layout with resizable panels:
   - Left: file tree (`main.tex`, `references.bib`, ...).
   - Center: CodeMirror LaTeX editor.
   - Right: agent panel (chat, tool trace, citation cards, patch review).
   - Bottom drawer (toggleable): PDF preview | citation graph tabs.
   - Top bar: project name, Compile button (with spinner/status), Import Paper button, connection status.

### 16.2 Editor behavior

- Debounced autosave (1.5s idle) → `PUT` with `explicit: false`; Cmd+S / Save button → `explicit: true`.
- Dirty indicator; 409 handling exactly per 14.3.
- Selection is mirrored into `agentStore` so the agent panel can send `selected_text`.
- "Insert citation" places `\cite{key}` at the cursor (or wraps selection end), then triggers the BibTeX append flow.

### 16.3 Agent panel behavior

- Streams via `lib/stream.ts` (14.6); renders `message_delta` as assistant text.
- Tool trace list: one row per `tool_call`, updated by matching `tool_result` — `✓ retrieve_evidence: found 8 candidate papers`, `✗ patch_latex_file: anchor_not_found`.
- `citation_suggestions` renders CitationSuggestionCard list: title, authors/year, **reason**, evidence snippet, score bar, and actions — Insert citation (if `bibtex_key`), Import paper (if `is_stub` or not imported), Show in graph.
- `patch_proposal` renders PatchReviewCard: before/after preview, Accept (POST to accept endpoint) / Reject.
- Stop button aborts the fetch.

### 16.4 Graph panel

- Fetches `/api/graph/neighborhood`, converts to `@xyflow/react` nodes/edges.
- Simple radial layout: seed centered; references left; citers right; concept-linked below. No force simulation for MVP.
- Stub nodes rendered dimmed/dashed with an "Import" affordance. Node click → metadata popover.
- "Enrich graph" button → triggers `expand_citation_graph_job` → poll → refetch.

### 16.5 Paper search dialog

Search input → `POST /api/papers/search` → result rows (title, year, authors, cited-by, abstract expander) → Import button → job polling (14.4) → success toast + project paper list refresh.

---

## 17. Testing Strategy

Unit (no containers needed): DOI normalization; abstract reconstruction; dedup match order; BibTeX key generation + LaTeX escaping (hostile-title fixture); RRF fusion math; anchor patcher (0/1/2 matches, stale version); path sanitizer.

Integration (against compose services): project + file CRUD with version semantics; paper import end-to-end with `openalex_work.json` fixture and `FakeEmbeddingClient` (assert Postgres rows, stub rows, citation edges, Neo4j nodes/edges); vector search with fake embeddings; **agent stream event-sequence test with `FakeLLMClient`** (the single highest-value test in the repo).

Rules: external APIs never called in tests; `FakeLLMClient` is scriptable (queue of responses, including tool calls); `FakeEmbeddingClient` returns deterministic vectors (hash-seeded) so vector tests are stable.

Frontend: optional for MVP; if time allows, one Playwright flow (create project → edit → save → search/import paper).

---

## 18. Observability

structlog JSON to stdout. Log with stable event names: `paper.search`, `paper.import.started/completed/failed`, `embed.started/completed/failed`, `graph.sync.started/completed/failed`, `agent.session.created`, `agent.tool.started/completed/failed`, `latex.compile.started/completed/failed`. Include `project_id`, `job_id`/`session_id`, duration_ms.

`tool_calls.result` is truncated to ≤ 4 KB before storage with `{"truncated": true}` added — `retrieve_evidence` results would otherwise bloat the table within a day of use. Never log raw LLM responses at info level.

---

## 19. Security

1. **LaTeX**: no shell escape; sandboxed temp workdir; timeout; path sanitizer everywhere; output size cap; network-free compile (enabled by the pre-warmed bundle).
2. **Agent tools**: no arbitrary SQL/Cypher/shell/filesystem tools, ever. Narrow, typed, logged.
3. **Project boundary**: every project-scoped tool and route takes `project_id` and validates existence; signatures are ready for real per-user authorization later.
4. **MCP**: stdio only. Before any Streamable HTTP exposure, add authentication — the server has full DB access.
5. **External APIs**: retries with backoff; Redis cache; polite-pool `mailto` mandatory for OpenAlex.
6. **Secrets**: env only; `.env` gitignored; `.env.example` committed.

---

## 20. Implementation Milestones

Complete in order. Each milestone ends with its acceptance criteria verified.

### M0 — Bootstrap
Monorepo skeleton, Docker Compose (Section 5 verbatim), Dockerfiles, Makefile, `.env.example`.
**Accept:** `docker compose up --build` brings up all six services healthy on cold start (healthchecks green); `GET :8000/api/health` returns per-service ok; `:3000` renders a placeholder.

### M1 — Backend foundation
FastAPI app factory, settings, structlog, async engine/session, Neo4j driver lifecycle, Redis client, CORS middleware (14.2), health endpoint checking all three stores, Neo4j constraint bootstrap on startup.
**Accept:** health reflects real connectivity; killing postgres flips its health field; tests pass.

### M2 — Models, migrations, project/file CRUD
All Section 6 tables via Alembic (extension in first migration); dev-user seed; project CRUD; file CRUD with the versioning policy (6.1) and 409 semantics (14.3); bootstrap files on project create (15.1).
**Accept:** create project → `main.tex` + `references.bib` exist; explicit save bumps version + snapshots; autosave doesn't; stale write → 409 with current content.

### M3 — Frontend workspace shell
Project list, workspace layout, file tree, CodeMirror editor with save/autosave/409 handling, agent panel placeholder, PDF/graph drawer placeholders.
**Accept:** edit `main.tex`, Cmd+S, refresh — content persists; 409 flow behaves per 14.3.

### M4 — OpenAlex search + import (with stubs)
OpenAlex client (polite pool, Redis cache, tenacity), normalization + DOI rules (8.2), dedup upsert (8.3), stub creation + citation edges (8.4), arq worker + `ingest_paper`, `jobs` table + `GET /api/jobs/{id}`, paper search dialog + import flow in UI.
**Accept:** import one real paper → Postgres has the paper, N stub rows, N citation edges; re-import is a no-op (dedup); import via fixture in tests; UI shows the paper in the project list after polling.

### M5 — Neo4j sync
`graph/sync.py` MERGE logic; sync on ingest; `resync_graph()` + make target; neighborhood endpoint using capped queries (7.4).
**Accept:** imported paper + stubs visible in Neo4j browser; `citations_cited_idx` era queries return; neighborhood endpoint returns nodes/edges with `is_stub` flags; wiping Neo4j + `make resync-graph` restores everything.

### M6 — Embeddings + vector search
Embedding client interface + one provider + Fake; startup dim assertion (2.4); embed job; vector search endpoint.
**Accept:** imported papers get one `title_abstract` chunk with an embedding; vector search returns sensible results; tests use only the Fake.

### M7 — Hybrid RRF retrieval
Graph search lists (coupling/co-citation/shared-concepts/neighbors), `fusion.py` RRF, `hybrid.py` orchestration, `explain.py` reasons, `retrieve_evidence` core tool.
**Accept:** given a paragraph, ranked evidence returns with `retrieval_sources` and human-readable reasons; results include both vector-only and graph-only candidates; `test_fusion.py` + `test_hybrid_retrieval.py` pass.

### M8 — Agent loop + streaming
Session tables wiring, tool registry, orchestrator loop (11.2), streaming endpoint (14.5), frontend stream client (14.6), tool trace UI, citation suggestion cards. **No intent classifier.**
**Accept:** select text → ask for citations → trace shows `inspect_latex_project`, `retrieve_evidence`, `rank_related_work` → suggestion cards render with reasons; `test_agent_stream.py` passes; Stop button aborts cleanly.

### M9 — BibTeX + citation insertion
Crossref content-negotiation client, fallback generator with escaping, key generation + collision handling, insert-citation flow, patch-accept endpoint, `references.bib` append with dedup.
**Accept:** Insert citation → `\cite{key}` in `main.tex`, correct entry in `references.bib`, `project_papers` row created; second insert of same paper reuses the key and does not duplicate the entry; hostile-title paper produces compilable BibTeX.

### M10 — LaTeX compilation
Tectonic in worker image with pre-warmed bundle (15.2), compile job (15.3), compile + status + PDF routes, PDF preview panel.
**Accept:** Compile button → PDF renders in the drawer; a deliberate LaTeX error shows the log excerpt in the UI; compile works with worker network disabled (proves the warm bundle).

### M11 — MCP server
FastMCP server, all ten tools registered as thin wrappers, README section with MCP Inspector + Claude Desktop config.
**Accept:** MCP Inspector lists ten tools; `search_papers`, `get_citation_neighborhood`, `retrieve_evidence` calls succeed and are logged to `tool_calls`; Claude Desktop can drive an import end-to-end.

### M12 — Polish
README with architecture diagram (mermaid), demo GIF/screenshots, seeded demo project script (creates a project + imports 3 fixed papers + enriches stubs), tool-trace and graph screenshots, System Design Notes section.
**Accept:** a stranger runs `make up`, follows the README, and completes the Section 22 demo in under 3 minutes.

---

## 21. Definition of Done

- Runs locally with `docker compose up --build` from a cold clone.
- Write LaTeX; import papers from OpenAlex; papers + stubs in Postgres; graph mirrored in Neo4j; chunks embedded in pgvector.
- Agent recommends citations via hybrid RRF retrieval with visible tool traces and human-readable reasons.
- Insert citation + BibTeX works, including hostile titles.
- Compile to PDF with the pre-warmed sandboxed Tectonic.
- MCP server exposes the ten tools; verified with Inspector and one real client.
- `resync_graph` rebuilds Neo4j from Postgres.
- All listed tests pass with zero external API calls.

## 22. End-to-End Acceptance Script

```text
1.  docker compose up --build            # cold start, all healthchecks green
2.  Open localhost:3000; create project "GraphRAG Literature Review".
3.  Edit main.tex; Cmd+S; refresh; content persists.
4.  Search OpenAlex: "graph retrieval augmented generation".
5.  Import 3 papers; watch job status resolve.
6.  psql: confirm papers rows, stub rows (is_stub=true), citations rows.
7.  Neo4j browser: confirm Paper nodes (incl. stubs) and CITES edges.
8.  psql: confirm paper_chunks rows with non-null embeddings.
9.  Open graph drawer; click "Enrich graph"; watch stubs promote.
10. Select the intro paragraph; ask agent for citation suggestions.
11. Confirm tool trace: inspect_latex_project → retrieve_evidence → rank_related_work.
12. Confirm suggestion cards show reasons mentioning graph signals.
13. Insert one citation; confirm \cite{...} and references.bib entry.
14. Compile; confirm PDF preview.
15. Run MCP Inspector; call search_papers and retrieve_evidence.
16. make resync-graph after wiping Neo4j; confirm graph restored.
```
