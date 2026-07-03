# CitePilot Architecture and Implementation Blueprint

**Project:** CitePilot  
**Concept:** An Overleaf + Cursor-style research workspace with a LaTeX editor on one side and an agentic GraphRAG research assistant on the other.  
**Goal:** Build a full-stack AI tooling system that demonstrates React/TypeScript, Python backend infrastructure, scientific data ingestion, knowledge graphs, GraphRAG, agentic tool use, and MCP tooling.

---

## 0. How to Use This File With a Coding Agent

Give this file to an implementation agent and tell it:

> Implement CitePilot exactly according to this blueprint. Work milestone by milestone. Do not skip migrations, tests, logging, or acceptance checks. When a feature requires external APIs, create a mock fixture first, then add the real API integration. Always keep the app runnable with Docker Compose.

The coding agent should follow these rules:

1. **One milestone at a time.** Do not jump to advanced agent features until the project boots, persists data, and renders a LaTeX project.
2. **Every milestone must have acceptance criteria.** The agent should run the app, verify endpoints, and add tests where appropriate.
3. **Keep the backend modular.** The graph layer, vector layer, LLM layer, paper ingestion layer, and MCP layer should be separate modules.
4. **Never hardcode API keys.** All secrets must come from environment variables.
5. **Use local fixtures for tests.** Do not call OpenAlex, Semantic Scholar, Crossref, or LLM APIs in unit tests.
6. **Prefer small, observable steps.** Every agent action, retrieval call, tool invocation, and LaTeX patch should be logged.
7. **Optimize for interview explanation.** The final project should make it easy to explain the architecture, tradeoffs, data flow, and system design.

---

## 1. Product Vision

CitePilot is a research-writing environment that lets a user write LaTeX while an AI agent reasons over a citation-aware scientific knowledge graph.

The app should feel like:

- **Overleaf:** project files, LaTeX editor, BibTeX manager, PDF preview.
- **Cursor:** AI side panel, contextual editing, tool traces, patch suggestions.
- **GraphRAG research assistant:** citation graph traversal, semantic retrieval, paper neighborhoods, research gap discovery, related-work generation.

The core idea is that researchers do not only need semantically similar text chunks. They need **relationship-aware retrieval**:

```text
Paper A
  -> cites Paper B
  -> is cited by Paper C
  -> shares Method X with Paper D
  -> evaluates on Dataset Y
  -> appears in the same citation neighborhood as Paper E
```

This makes the project much stronger than a normal PDF chatbot.

---

## 2. What This Project Should Demonstrate

This project should demonstrate that you can build:

1. **Full-stack AI tooling**
   - React/TypeScript frontend.
   - Python backend.
   - Linux/Docker-based development environment.
   - Database-backed application state.
   - Worker queue for async ingestion and compilation.

2. **RAG and GraphRAG systems**
   - Vector search over paper chunks.
   - Graph traversal over citation relationships.
   - Hybrid retrieval that combines semantic similarity with graph structure.
   - Evidence-grounded generation with citations.

3. **Knowledge graph modeling**
   - Papers, authors, venues, concepts, methods, datasets, and citation edges.
   - Neo4j constraints and Cypher queries.
   - Graph expansion, centrality, co-citation, and bibliographic coupling.

4. **Agentic workflows**
   - An AI agent that calls tools instead of only chatting.
   - Tool traces shown to the user.
   - MCP tools that expose retrieval, graph, citation, and LaTeX operations.
   - Safe patch application to LaTeX documents.

5. **Production-style engineering**
   - Docker Compose.
   - Alembic migrations.
   - Structured logging.
   - Job queue.
   - Caching.
   - Basic tests.
   - Clear boundaries between services.

---

## 3. Source Documentation to Anchor Implementation

Use these official or primary docs as the source of truth while implementing:

- MCP specification: https://modelcontextprotocol.io/specification/2025-06-18
- MCP tools spec: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- OpenAlex API docs: https://developers.openalex.org/
- OpenAlex Works docs: https://developers.openalex.org/api-reference/works
- Semantic Scholar Academic Graph API docs: https://api.semanticscholar.org/api-docs/
- Semantic Scholar product API page: https://www.semanticscholar.org/product/api
- Crossref REST API docs: https://api.crossref.org/
- Neo4j GraphRAG Python docs: https://neo4j.com/docs/neo4j-graphrag-python/current/
- Neo4j GraphRAG Python GitHub: https://github.com/neo4j/neo4j-graphrag-python
- pgvector GitHub: https://github.com/pgvector/pgvector
- FastAPI docs: https://fastapi.tiangolo.com/
- Next.js docs: https://nextjs.org/docs
- Tectonic LaTeX engine: https://tectonic-typesetting.github.io/

---

## 4. MVP Scope

### 4.1 Build This First

The first complete demo should support this user flow:

1. User creates a project.
2. User sees a browser-based LaTeX editor with `main.tex`.
3. User searches for a paper using OpenAlex.
4. User imports the paper.
5. Backend stores paper metadata in Postgres.
6. Backend creates graph nodes and edges in Neo4j.
7. Backend embeds the paper abstract/chunks into pgvector.
8. User asks the AI panel: “What related work should I cite for this paragraph?”
9. Agent calls retrieval tools.
10. Agent expands the citation graph around relevant papers.
11. Agent returns ranked citation suggestions with explanations.
12. User clicks “Insert citation.”
13. App inserts `\cite{...}` into LaTeX and adds the BibTeX entry.
14. User compiles LaTeX and sees a PDF preview.

### 4.2 Do Not Build These Yet

Avoid these until after the MVP:

- Real-time collaborative editing.
- Full Overleaf-level project management.
- Full PDF parsing for every publisher.
- Complex multi-user permissions.
- Fine-tuned local LLMs.
- Kubernetes deployment.
- Full citation style formatting.
- Payment system.

---

## 5. Exact Technology Stack

### 5.1 Frontend

Use:

- **Next.js App Router** for frontend app structure.
- **React** for UI.
- **TypeScript** for all frontend code.
- **Tailwind CSS** for styling.
- **shadcn/ui** for base UI components.
- **CodeMirror 6** via `@uiw/react-codemirror` for the LaTeX editor.
- **TanStack Query** for API fetching, caching, and mutations.
- **Zustand** for local UI/editor state.
- **Zod** for client-side schema validation.
- **React Hook Form** where forms are needed.
- **@xyflow/react** for the graph visualization panel in the MVP.
- **Server-Sent Events or WebSocket** for streaming agent responses.

Why CodeMirror instead of Monaco for MVP:

- CodeMirror is lighter and easier to customize for browser-based document editing.
- Monaco is excellent for code IDEs, but CodeMirror is usually easier for custom writing/editor UX.
- You can switch to Monaco later if you want a more Cursor-like coding feel.

### 5.2 Backend API

Use:

- **Python 3.12**.
- **FastAPI** for the HTTP API.
- **Uvicorn** as ASGI server.
- **Pydantic v2** for request/response models.
- **pydantic-settings** for environment configuration.
- **SQLAlchemy 2.0** for Postgres ORM/core access.
- **Alembic** for database migrations.
- **asyncpg** for Postgres connection.
- **neo4j Python driver** for Neo4j operations.
- **httpx** for external API requests.
- **tenacity** for retry logic.
- **structlog** or Python logging with JSON formatter for structured logs.
- **pytest** for tests.
- **ruff** for linting/formatting.
- **mypy** optional, but recommended if time allows.

### 5.3 Data Storage

Use:

- **Postgres** as the durable relational database.
- **pgvector** extension for vector similarity search.
- **Neo4j** as the graph database.
- **Redis** for cache, session state, and queue backend.

Why both Postgres/pgvector and Neo4j:

- Postgres stores durable app data: users, projects, files, papers, chunks, embeddings, jobs, messages, tool calls.
- pgvector enables vector search directly beside structured metadata.
- Neo4j handles graph traversal, citation neighborhoods, co-citation, bibliographic coupling, and graph visualization queries.
- This separation makes the system easy to explain: Postgres is the app memory; Neo4j is the relationship reasoning layer.

### 5.4 Worker Queue

Use:

- **Redis Queue (RQ)** for MVP background jobs.

Jobs:

- `ingest_paper_job`
- `expand_citation_graph_job`
- `embed_paper_chunks_job`
- `compile_latex_job`
- `extract_concepts_job`

Why RQ instead of Celery at first:

- Easier setup.
- Redis-only.
- Enough for an MVP.
- You can later replace with Celery, Dramatiq, Kafka, or Redpanda.

### 5.5 Scientific Metadata Sources

Use in this order:

1. **OpenAlex** as the default source.
   - Broad coverage.
   - Open API.
   - Useful metadata for works, authors, sources, concepts/topics, references, and citation counts.

2. **Semantic Scholar Academic Graph API** as optional enrichment.
   - Useful for paper details, citations, references, authors, venues, abstracts, and fields of study.
   - Add an API key later for better rate limits.

3. **Crossref** as fallback for DOI/BibTeX-style metadata.
   - Useful when DOI is known.

4. **arXiv API** as optional future source for open preprints.

### 5.6 LLM and Embedding Layer

Do **not** hardcode one model provider throughout the app. Create an adapter layer:

```text
backend/app/llm/
  base.py
  openai_client.py
  anthropic_client.py
  local_client.py
  prompts.py
```

For the MVP, support one cloud provider through environment variables:

```env
LLM_PROVIDER=openai
LLM_MODEL=<model-name>
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=<embedding-model-name>
EMBEDDING_DIM=1536
```

The code should be model-agnostic:

```python
class LLMClient(Protocol):
    async def complete(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse: ...

class EmbeddingClient(Protocol):
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

This makes the system more production-like and avoids locking the architecture to one vendor.

### 5.7 MCP Layer

Use:

- **Official MCP Python SDK** or **FastMCP**.
- Use **stdio transport** for local IDE/agent integration.
- Use **Streamable HTTP** later if you want the web app to connect to the MCP server over the network.

MCP should expose graph and project operations as tools:

```text
search_papers
import_paper
get_paper
get_citation_neighborhood
rank_related_work
retrieve_evidence
suggest_bibtex
inspect_latex_project
patch_latex_file
compile_latex
find_research_gaps
```

### 5.8 LaTeX Compilation

Use:

- **Tectonic** for MVP LaTeX compilation.
- Run compilation in a separate worker job.
- Run compilation inside a sandboxed container or restricted process.
- Disable shell escape.
- Apply timeouts.
- Store compiled PDF output as a file artifact.

Why Tectonic:

- Modernized LaTeX engine.
- Self-contained relative to classic full TeXLive setups.
- Easier for Dockerized MVP than managing a full Overleaf-style toolchain.

---

## 6. System Architecture

### 6.1 High-Level Architecture

```mermaid
flowchart LR
    U[User Browser] --> FE[Next.js Frontend]
    FE --> API[FastAPI Backend]
    FE --> STREAM[Agent Streaming Endpoint]

    API --> PG[(Postgres + pgvector)]
    API --> NEO[(Neo4j)]
    API --> REDIS[(Redis)]
    API --> WORKER[RQ Workers]

    WORKER --> PG
    WORKER --> NEO
    WORKER --> EXT[OpenAlex / Semantic Scholar / Crossref]
    WORKER --> LATEX[Tectonic LaTeX Compiler]

    API --> MCP[MCP Server]
    MCP --> PG
    MCP --> NEO
    MCP --> WORKER

    API --> LLM[LLM Provider]
    API --> EMB[Embedding Provider]
```

### 6.2 Service Responsibilities

#### Frontend

Responsible for:

- Rendering project workspace.
- Managing LaTeX editor state.
- Showing PDF preview.
- Showing AI chat and streaming output.
- Showing tool traces.
- Showing citation recommendations.
- Showing graph visualization.
- Letting user accept/reject LaTeX patches.

Not responsible for:

- Calling OpenAlex directly.
- Running LLM requests directly.
- Writing directly to Neo4j/Postgres.
- Compiling LaTeX.

#### FastAPI Backend

Responsible for:

- Authentication placeholder or simple local user mode.
- Project/file CRUD.
- Paper search/import endpoints.
- Agent endpoint.
- Retrieval orchestration.
- Tool execution.
- Job enqueueing.
- PDF result serving.

#### Worker

Responsible for:

- Slow external API calls.
- Paper enrichment.
- Embeddings.
- Graph updates.
- LaTeX compilation.

#### Postgres

Responsible for:

- Durable app state.
- Paper metadata.
- Chunks and embeddings.
- File versions.
- Agent sessions.
- Tool call logs.

#### Neo4j

Responsible for:

- Citation graph.
- Author graph.
- Venue graph.
- Concept/method/dataset graph.
- Graph traversal queries.
- Neighborhood extraction.

#### MCP Server

Responsible for:

- Exposing safe, typed tools to AI agents.
- Keeping graph/project operations reusable outside the web app.
- Demonstrating standardized agent tool integration.

---

## 7. Repository Structure

Use a monorepo:

```text
citepilot/
  README.md
  docker-compose.yml
  .env.example
  .gitignore
  Makefile

  apps/
    web/
      package.json
      next.config.ts
      tsconfig.json
      app/
        layout.tsx
        page.tsx
        projects/
          [projectId]/
            page.tsx
      components/
        editor/
          LatexEditor.tsx
          FileTree.tsx
          PdfPreview.tsx
        agent/
          AgentPanel.tsx
          ToolTrace.tsx
          CitationSuggestionCard.tsx
        graph/
          CitationGraph.tsx
        ui/
          ...shadcn components...
      lib/
        api.ts
        schemas.ts
        queryClient.ts
        stream.ts
      stores/
        editorStore.ts
        agentStore.ts

  backend/
    pyproject.toml
    alembic.ini
    alembic/
      env.py
      versions/
    app/
      main.py
      config.py
      logging.py
      deps.py

      api/
        router.py
        routes/
          health.py
          projects.py
          files.py
          papers.py
          graph.py
          agent.py
          latex.py

      db/
        postgres.py
        models.py
        migrations_notes.md

      graph/
        neo4j_client.py
        schema.py
        queries.py
        sync.py

      retrieval/
        chunking.py
        embeddings.py
        vector_search.py
        graph_search.py
        hybrid.py
        ranking.py

      ingestion/
        openalex.py
        semantic_scholar.py
        crossref.py
        normalize.py
        bibtex.py
        jobs.py

      latex/
        compiler.py
        patcher.py
        sanitizer.py

      agent/
        orchestrator.py
        planner.py
        tool_registry.py
        tools.py
        prompts.py
        schemas.py
        safety.py

      llm/
        base.py
        providers.py
        openai_client.py
        anthropic_client.py
        local_client.py

      mcp_server/
        server.py
        tools.py
        schemas.py

      workers/
        rq_app.py
        jobs.py

      tests/
        test_health.py
        test_openalex_normalize.py
        test_hybrid_retrieval.py
        test_latex_patcher.py
        fixtures/
          openalex_work.json
          semantic_scholar_paper.json

  infra/
    docker/
      backend.Dockerfile
      web.Dockerfile
      worker.Dockerfile
      latex.Dockerfile
    scripts/
      init_neo4j.cypher
      init_postgres.sql
```

---

## 8. Environment Variables

Create `.env.example`:

```env
# App
APP_ENV=development
APP_NAME=CitePilot
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000

# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=citepilot
POSTGRES_USER=citepilot
POSTGRES_PASSWORD=citepilot
DATABASE_URL=postgresql+asyncpg://citepilot:citepilot@postgres:5432/citepilot

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=citepilot-password

# Redis
REDIS_URL=redis://redis:6379/0

# External scholarly APIs
OPENALEX_MAILTO=your_email@example.com
SEMANTIC_SCHOLAR_API_KEY=
CROSSREF_MAILTO=your_email@example.com

# LLM
LLM_PROVIDER=openai
LLM_MODEL=
LLM_API_KEY=

# Embeddings
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=
EMBEDDING_DIM=1536

# LaTeX
LATEX_WORKDIR=/tmp/citepilot-latex
LATEX_COMPILE_TIMEOUT_SECONDS=30

# Security / dev auth
DEV_USER_ID=00000000-0000-0000-0000-000000000001
```

---

## 9. Docker Compose

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: citepilot-postgres
    environment:
      POSTGRES_DB: citepilot
      POSTGRES_USER: citepilot
      POSTGRES_PASSWORD: citepilot
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/scripts/init_postgres.sql:/docker-entrypoint-initdb.d/init_postgres.sql

  neo4j:
    image: neo4j:5-community
    container_name: citepilot-neo4j
    environment:
      NEO4J_AUTH: neo4j/citepilot-password
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs

  redis:
    image: redis:7
    container_name: citepilot-redis
    ports:
      - "6379:6379"

  backend:
    build:
      context: .
      dockerfile: infra/docker/backend.Dockerfile
    container_name: citepilot-backend
    env_file: .env
    depends_on:
      - postgres
      - neo4j
      - redis
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app/backend
      - latex_artifacts:/tmp/citepilot-latex
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build:
      context: .
      dockerfile: infra/docker/worker.Dockerfile
    container_name: citepilot-worker
    env_file: .env
    depends_on:
      - postgres
      - neo4j
      - redis
    volumes:
      - ./backend:/app/backend
      - latex_artifacts:/tmp/citepilot-latex
    command: python -m app.workers.rq_app

  web:
    build:
      context: .
      dockerfile: infra/docker/web.Dockerfile
    container_name: citepilot-web
    env_file: .env
    depends_on:
      - backend
    ports:
      - "3000:3000"
    volumes:
      - ./apps/web:/app/apps/web
      - /app/apps/web/node_modules
    command: pnpm dev --host 0.0.0.0

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  latex_artifacts:
```

---

## 10. Postgres Schema

### 10.1 Design Principle

Postgres should store canonical app data. Neo4j should store graph-optimized copies of selected entities and relationships.

Postgres is the source of truth for:

- projects
- files
- papers
- paper chunks
- embeddings
- agent sessions
- tool calls
- compile jobs

Neo4j is the source of truth for:

- graph traversal relationships
- paper neighborhood expansion
- co-citation queries
- author/concept relationship queries

### 10.2 Core Tables

Create these tables with Alembic.

#### users

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE,
  display_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

For MVP, create one dev user automatically.

#### projects

```sql
CREATE TABLE projects (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### project_files

```sql
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
```

#### file_versions

```sql
CREATE TABLE file_versions (
  id UUID PRIMARY KEY,
  file_id UUID NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
  version INT NOT NULL,
  content TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'user',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(file_id, version)
);
```

#### papers

```sql
CREATE TABLE papers (
  id UUID PRIMARY KEY,
  openalex_id TEXT UNIQUE,
  semantic_scholar_id TEXT UNIQUE,
  doi TEXT UNIQUE,
  title TEXT NOT NULL,
  abstract TEXT,
  publication_year INT,
  publication_date DATE,
  venue_name TEXT,
  source_name TEXT,
  cited_by_count INT DEFAULT 0,
  url TEXT,
  pdf_url TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### authors

```sql
CREATE TABLE authors (
  id UUID PRIMARY KEY,
  openalex_id TEXT UNIQUE,
  semantic_scholar_id TEXT UNIQUE,
  name TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'
);
```

#### paper_authors

```sql
CREATE TABLE paper_authors (
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
  author_order INT,
  PRIMARY KEY (paper_id, author_id)
);
```

#### citations

```sql
CREATE TABLE citations (
  citing_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  cited_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'openalex',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (citing_paper_id, cited_paper_id)
);
```

#### concepts

```sql
CREATE TABLE concepts (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL DEFAULT 'concept',
  metadata JSONB NOT NULL DEFAULT '{}'
);
```

Concept `type` can be:

```text
concept
method
dataset
task
metric
field
```

#### paper_concepts

```sql
CREATE TABLE paper_concepts (
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  score FLOAT,
  source TEXT NOT NULL DEFAULT 'openalex',
  PRIMARY KEY (paper_id, concept_id)
);
```

#### paper_chunks

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE paper_chunks (
  id UUID PRIMARY KEY,
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  section TEXT,
  text TEXT NOT NULL,
  token_count INT,
  embedding vector(1536),
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(paper_id, chunk_index)
);
```

Create vector index:

```sql
CREATE INDEX paper_chunks_embedding_hnsw_idx
ON paper_chunks
USING hnsw (embedding vector_cosine_ops);
```

#### project_papers

```sql
CREATE TABLE project_papers (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  bibtex_key TEXT NOT NULL,
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, paper_id),
  UNIQUE(project_id, bibtex_key)
);
```

#### agent_sessions

```sql
CREATE TABLE agent_sessions (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  title TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### agent_messages

```sql
CREATE TABLE agent_messages (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### tool_calls

```sql
CREATE TABLE tool_calls (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL DEFAULT '{}',
  result JSONB,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
```

#### jobs

```sql
CREATE TABLE jobs (
  id UUID PRIMARY KEY,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  input JSONB NOT NULL DEFAULT '{}',
  result JSONB,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### latex_compilations

```sql
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

---

## 11. Neo4j Graph Schema

### 11.1 Node Types

Use these labels:

```text
Paper
Author
Venue
Concept
Method
Dataset
Task
Metric
Project
LatexSection
```

### 11.2 Paper Node

```text
(:Paper {
  id: string,                  // UUID from Postgres
  openalex_id: string,
  semantic_scholar_id: string,
  doi: string,
  title: string,
  year: integer,
  cited_by_count: integer,
  url: string
})
```

### 11.3 Author Node

```text
(:Author {
  id: string,
  openalex_id: string,
  name: string
})
```

### 11.4 Concept/Method/Dataset Nodes

```text
(:Concept {id: string, name: string})
(:Method {id: string, name: string})
(:Dataset {id: string, name: string})
(:Task {id: string, name: string})
(:Metric {id: string, name: string})
```

### 11.5 Relationships

```text
(:Paper)-[:CITES]->(:Paper)
(:Paper)-[:WRITTEN_BY {author_order: int}]->(:Author)
(:Paper)-[:PUBLISHED_IN]->(:Venue)
(:Paper)-[:MENTIONS_CONCEPT {score: float, source: string}]->(:Concept)
(:Paper)-[:USES_METHOD {confidence: float, source: string}]->(:Method)
(:Paper)-[:EVALUATES_ON {confidence: float, source: string}]->(:Dataset)
(:Paper)-[:ADDRESSES_TASK {confidence: float, source: string}]->(:Task)
(:Paper)-[:REPORTS_METRIC {confidence: float, source: string}]->(:Metric)
(:LatexSection)-[:CITES]->(:Paper)
(:LatexSection)-[:ABOUT]->(:Concept)
```

### 11.6 Neo4j Constraints

Create `infra/scripts/init_neo4j.cypher`:

```cypher
CREATE CONSTRAINT paper_id_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE;

CREATE CONSTRAINT author_id_unique IF NOT EXISTS
FOR (a:Author) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT concept_name_unique IF NOT EXISTS
FOR (c:Concept) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT method_name_unique IF NOT EXISTS
FOR (m:Method) REQUIRE m.name IS UNIQUE;

CREATE CONSTRAINT dataset_name_unique IF NOT EXISTS
FOR (d:Dataset) REQUIRE d.name IS UNIQUE;

CREATE INDEX paper_title_index IF NOT EXISTS
FOR (p:Paper) ON (p.title);

CREATE INDEX paper_year_index IF NOT EXISTS
FOR (p:Paper) ON (p.year);
```

### 11.7 Core Cypher Queries

#### Get citation neighborhood

```cypher
MATCH (seed:Paper {id: $paper_id})
MATCH path = (seed)-[:CITES*1..2]-(neighbor:Paper)
RETURN seed, neighbor, relationships(path) AS rels, length(path) AS distance
LIMIT $limit;
```

#### Papers that cite this paper

```cypher
MATCH (citing:Paper)-[:CITES]->(seed:Paper {id: $paper_id})
RETURN citing
ORDER BY citing.cited_by_count DESC
LIMIT $limit;
```

#### Papers this paper cites

```cypher
MATCH (seed:Paper {id: $paper_id})-[:CITES]->(cited:Paper)
RETURN cited
ORDER BY cited.cited_by_count DESC
LIMIT $limit;
```

#### Bibliographic coupling

Papers that cite many of the same references as the seed paper.

```cypher
MATCH (seed:Paper {id: $paper_id})-[:CITES]->(ref:Paper)<-[:CITES]-(other:Paper)
WHERE other.id <> seed.id
RETURN other, count(ref) AS shared_references
ORDER BY shared_references DESC, other.cited_by_count DESC
LIMIT $limit;
```

#### Co-citation

Papers that are often cited together with the seed paper.

```cypher
MATCH (citing:Paper)-[:CITES]->(seed:Paper {id: $paper_id})
MATCH (citing)-[:CITES]->(other:Paper)
WHERE other.id <> seed.id
RETURN other, count(citing) AS co_citation_count
ORDER BY co_citation_count DESC, other.cited_by_count DESC
LIMIT $limit;
```

#### Shared concepts

```cypher
MATCH (seed:Paper {id: $paper_id})-[:MENTIONS_CONCEPT]->(c:Concept)<-[:MENTIONS_CONCEPT]-(other:Paper)
WHERE other.id <> seed.id
RETURN other, collect(c.name) AS shared_concepts, count(c) AS concept_overlap
ORDER BY concept_overlap DESC, other.cited_by_count DESC
LIMIT $limit;
```

---

## 12. Paper Ingestion Design

### 12.1 Ingestion Flow

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as FastAPI
    participant W as Worker
    participant OA as OpenAlex
    participant PG as Postgres
    participant N as Neo4j
    participant E as Embedding Provider

    FE->>API: POST /papers/search
    API->>OA: Search works
    OA-->>API: Search results
    API-->>FE: Results

    FE->>API: POST /papers/import {openalex_id}
    API->>PG: Create job
    API->>W: Enqueue ingest_paper_job
    API-->>FE: job_id

    W->>OA: Fetch work details
    W->>PG: Upsert paper/authors/concepts/citations
    W->>N: Merge nodes/relationships
    W->>E: Embed abstract/chunks
    W->>PG: Store embeddings
    W->>PG: Mark job complete
```

### 12.2 OpenAlex Work Mapping

Map OpenAlex work fields into internal model:

```text
OpenAlex id                 -> papers.openalex_id
DOI                         -> papers.doi
Title                       -> papers.title
abstract_inverted_index     -> papers.abstract after reconstruction
publication_year            -> papers.publication_year
publication_date            -> papers.publication_date
primary_location.source     -> papers.venue_name / source_name
cited_by_count              -> papers.cited_by_count
referenced_works            -> citations edges
authorships                 -> authors and paper_authors
concepts/topics             -> concepts and paper_concepts
open_access.oa_url          -> papers.pdf_url if available
```

### 12.3 Abstract Reconstruction

OpenAlex abstracts may be stored as an inverted index. Implement:

```python
def reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for idx in idxs:
            positions.append((idx, word))
    return " ".join(word for _, word in sorted(positions))
```

### 12.4 Normalized Paper DTO

Create `backend/app/ingestion/normalize.py`:

```python
from pydantic import BaseModel

class NormalizedAuthor(BaseModel):
    source_id: str | None = None
    name: str
    order: int | None = None

class NormalizedConcept(BaseModel):
    name: str
    type: str = "concept"
    score: float | None = None
    source: str

class NormalizedCitation(BaseModel):
    source_id: str
    source: str

class NormalizedPaper(BaseModel):
    source: str
    source_id: str
    title: str
    doi: str | None = None
    abstract: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    venue_name: str | None = None
    cited_by_count: int | None = None
    url: str | None = None
    pdf_url: str | None = None
    authors: list[NormalizedAuthor] = []
    concepts: list[NormalizedConcept] = []
    references: list[NormalizedCitation] = []
    raw: dict = {}
```

All sources should normalize into this DTO before touching Postgres or Neo4j.

---

## 13. Chunking and Embeddings

### 13.1 MVP Chunking

For MVP, chunk only:

- title
- abstract
- imported metadata summary
- optional citation context

Create chunks like:

```text
Chunk 0: Title + abstract
Chunk 1: Concepts/topics summary
Chunk 2: Citation metadata summary
```

Later, add PDF/full-text extraction.

### 13.2 Chunk Object

```python
class Chunk(BaseModel):
    paper_id: UUID
    chunk_index: int
    section: str
    text: str
    token_count: int | None = None
    metadata: dict = {}
```

### 13.3 Vector Search Query

Use cosine distance:

```sql
SELECT
  pc.id,
  pc.paper_id,
  pc.text,
  pc.section,
  p.title,
  p.publication_year,
  p.cited_by_count,
  1 - (pc.embedding <=> :query_embedding) AS similarity
FROM paper_chunks pc
JOIN papers p ON p.id = pc.paper_id
WHERE pc.embedding IS NOT NULL
ORDER BY pc.embedding <=> :query_embedding
LIMIT :limit;
```

### 13.4 Hybrid Retrieval Strategy

Given a user query or LaTeX section:

1. Embed the query.
2. Retrieve top 30 chunks from pgvector.
3. Extract paper IDs from those chunks.
4. For the top 5 seed paper IDs, query Neo4j for:
   - cited papers
   - citing papers
   - bibliographic coupling
   - co-citation papers
   - shared concept papers
5. Merge candidates.
6. Score candidates.
7. Retrieve supporting chunks.
8. Return ranked evidence.

### 13.5 Hybrid Score

Use this initial scoring formula:

```text
score =
  0.50 * vector_similarity
+ 0.20 * graph_relevance
+ 0.15 * citation_authority
+ 0.10 * recency_score
+ 0.05 * project_context_score
```

Definitions:

```text
vector_similarity:
  normalized cosine similarity from pgvector

graph_relevance:
  derived from graph path distance, shared references, co-citation count, and concept overlap

citation_authority:
  log-scaled cited_by_count

recency_score:
  higher for newer papers, but not so high that foundational papers disappear

project_context_score:
  boost papers already in the user's project or papers linked to project concepts
```

Use a simple implementation first. Avoid overengineering.

---

## 14. Agent Architecture

### 14.1 Agent Philosophy

The agent should not be a magical black box. It should be a tool-using assistant with visible steps.

The user should see:

```text
Thinking step summary:
- Searching project papers
- Running vector search
- Expanding citation graph
- Ranking candidate citations
- Drafting answer
- Suggesting LaTeX patch
```

Do not show hidden chain-of-thought. Show concise tool trace summaries.

### 14.2 Agent Flow

```mermaid
flowchart TD
    Q[User Question] --> INTENT[Classify Intent]
    INTENT --> PLAN[Create Tool Plan]
    PLAN --> TOOL[Execute Tool Calls]
    TOOL --> RETRIEVE[Collect Evidence]
    RETRIEVE --> ANSWER[Generate Grounded Answer]
    ANSWER --> PATCH{Needs LaTeX Patch?}
    PATCH -->|Yes| DIFF[Generate Diff]
    PATCH -->|No| DONE[Return Answer]
    DIFF --> REVIEW[User Reviews Patch]
    REVIEW --> APPLY[Apply Patch if Accepted]
```

### 14.3 Intent Types

Create enum:

```python
class AgentIntent(str, Enum):
    GENERAL_QA = "general_qa"
    RELATED_WORK = "related_work"
    CITATION_SUGGESTION = "citation_suggestion"
    RESEARCH_GAP = "research_gap"
    LATEX_EDIT = "latex_edit"
    BIBTEX_GENERATION = "bibtex_generation"
    GRAPH_EXPLORATION = "graph_exploration"
    COMPILE_HELP = "compile_help"
```

### 14.4 Tool Registry

Tools should be plain Python functions with Pydantic schemas. Then expose the same logic through:

1. FastAPI internal agent orchestrator.
2. MCP server tools.

Do not duplicate logic between API tools and MCP tools.

Structure:

```text
app/agent/tools.py          # core Python tool implementations
app/mcp_server/tools.py     # MCP wrappers around core tools
app/api/routes/agent.py     # web agent endpoint using same tools
```

### 14.5 Core Agent Tools

#### search_papers

Purpose: Search external scholarly APIs and/or local database.

Input:

```json
{
  "query": "graph rag scientific literature discovery",
  "source": "local_or_openalex",
  "year_min": 2018,
  "year_max": 2026,
  "limit": 10
}
```

Output:

```json
{
  "papers": [
    {
      "paper_id": "uuid-or-null",
      "external_id": "https://openalex.org/W...",
      "title": "...",
      "year": 2024,
      "authors": ["..."],
      "abstract": "...",
      "cited_by_count": 123,
      "imported": false
    }
  ]
}
```

#### import_paper

Purpose: Import paper metadata, citations, concepts, and embeddings.

Input:

```json
{
  "source": "openalex",
  "source_id": "https://openalex.org/W...",
  "project_id": "uuid"
}
```

Output:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

#### get_citation_neighborhood

Purpose: Query Neo4j for citation neighborhood.

Input:

```json
{
  "paper_id": "uuid",
  "depth": 2,
  "limit": 50,
  "include_citing": true,
  "include_cited": true,
  "include_shared_concepts": true
}
```

Output:

```json
{
  "nodes": [
    {"id": "uuid", "label": "Paper", "title": "...", "year": 2024}
  ],
  "edges": [
    {"source": "uuid", "target": "uuid", "type": "CITES"}
  ],
  "ranked_neighbors": [
    {"paper_id": "uuid", "reason": "cited by seed and shares 3 concepts", "score": 0.84}
  ]
}
```

#### retrieve_evidence

Purpose: Run hybrid vector + graph retrieval.

Input:

```json
{
  "project_id": "uuid",
  "query": "paragraph or user question",
  "seed_paper_ids": ["uuid"],
  "limit": 10
}
```

Output:

```json
{
  "evidence": [
    {
      "paper_id": "uuid",
      "title": "...",
      "chunk_id": "uuid",
      "text": "...",
      "score": 0.91,
      "retrieval_sources": ["vector", "citation_neighborhood"]
    }
  ]
}
```

#### rank_related_work

Purpose: Given a LaTeX section or paragraph, recommend papers.

Input:

```json
{
  "project_id": "uuid",
  "section_text": "...",
  "limit": 8
}
```

Output:

```json
{
  "recommendations": [
    {
      "paper_id": "uuid",
      "bibtex_key": "smith2024graphrag",
      "title": "...",
      "reason": "Strong match to the paragraph's discussion of graph-based retrieval and citation neighborhoods.",
      "evidence_snippets": ["..."],
      "score": 0.89
    }
  ]
}
```

#### suggest_bibtex

Purpose: Generate/return BibTeX for selected papers.

Input:

```json
{
  "paper_ids": ["uuid"],
  "project_id": "uuid"
}
```

Output:

```json
{
  "entries": [
    {
      "paper_id": "uuid",
      "bibtex_key": "smith2024graphrag",
      "bibtex": "@article{smith2024graphrag,...}"
    }
  ]
}
```

#### inspect_latex_project

Purpose: Let the agent read project files safely.

Input:

```json
{
  "project_id": "uuid",
  "paths": ["main.tex", "references.bib"]
}
```

Output:

```json
{
  "files": [
    {"path": "main.tex", "content": "...", "version": 3}
  ]
}
```

#### patch_latex_file

Purpose: Apply a controlled patch to a LaTeX file.

Input:

```json
{
  "project_id": "uuid",
  "path": "main.tex",
  "base_version": 3,
  "patch": "unified diff or structured edit"
}
```

Output:

```json
{
  "status": "applied",
  "new_version": 4
}
```

For MVP, use structured edits instead of raw diffs when possible:

```json
{
  "operation": "replace_range",
  "start_offset": 120,
  "end_offset": 260,
  "new_text": "..."
}
```

#### compile_latex

Purpose: Enqueue LaTeX compilation.

Input:

```json
{
  "project_id": "uuid",
  "main_file_path": "main.tex"
}
```

Output:

```json
{
  "compilation_id": "uuid",
  "status": "queued"
}
```

#### find_research_gaps

Purpose: Use graph + evidence to suggest possible gaps.

Input:

```json
{
  "project_id": "uuid",
  "seed_paper_id": "uuid",
  "focus": "multi-hop citation retrieval for scientific writing",
  "limit": 5
}
```

Output:

```json
{
  "gaps": [
    {
      "gap": "Most tools retrieve similar papers but do not expose citation-neighborhood reasoning to the writing interface.",
      "supporting_papers": ["uuid", "uuid"],
      "confidence": 0.72
    }
  ]
}
```

---

## 15. MCP Server Design

### 15.1 MCP Server File

Create:

```text
backend/app/mcp_server/server.py
```

Example shape:

```python
from mcp.server.fastmcp import FastMCP
from app.mcp_server.tools import register_tools

mcp = FastMCP("citepilot")
register_tools(mcp)

if __name__ == "__main__":
    mcp.run()
```

Depending on SDK version, import path may differ. Check the official MCP Python SDK docs during implementation.

### 15.2 Tool Registration Pattern

```python
def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def search_papers(query: str, limit: int = 10) -> dict:
        """Search local and external scholarly paper sources."""
        return await core_search_papers(query=query, limit=limit)

    @mcp.tool()
    async def get_citation_neighborhood(paper_id: str, depth: int = 2, limit: int = 50) -> dict:
        """Return citation-neighborhood graph nodes and edges for a paper."""
        return await core_get_citation_neighborhood(paper_id=paper_id, depth=depth, limit=limit)
```

### 15.3 MCP Tool Safety Rules

Each MCP tool must:

- Validate inputs with Pydantic.
- Log tool calls.
- Enforce project boundaries.
- Avoid returning huge payloads.
- Return structured JSON.
- Include human-readable summaries.
- Include stable IDs that the agent can reuse.

Do not expose dangerous tools like arbitrary SQL, arbitrary Cypher, shell commands, or unrestricted file reads.

### 15.4 MCP Tool List

Minimum MVP tools:

```text
search_papers
import_paper
get_paper
get_citation_neighborhood
retrieve_evidence
rank_related_work
suggest_bibtex
inspect_latex_project
patch_latex_file
compile_latex
```

Advanced tools:

```text
find_research_gaps
compare_papers
explain_citation_path
extract_claims
map_section_to_citations
```

---

## 16. FastAPI API Design

### 16.1 API Router Layout

```text
/api/health
/api/projects
/api/projects/{project_id}/files
/api/papers/search
/api/papers/import
/api/papers/{paper_id}
/api/graph/neighborhood
/api/agent/sessions
/api/agent/sessions/{session_id}/messages
/api/agent/stream
/api/latex/compile
/api/latex/compilations/{compilation_id}
```

### 16.2 Health

```http
GET /api/health
```

Response:

```json
{
  "status": "ok",
  "postgres": "ok",
  "neo4j": "ok",
  "redis": "ok"
}
```

### 16.3 Create Project

```http
POST /api/projects
```

Request:

```json
{
  "name": "GraphRAG Literature Review",
  "description": "Research writing project"
}
```

Response:

```json
{
  "id": "uuid",
  "name": "GraphRAG Literature Review"
}
```

On project creation, also create:

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

`references.bib`:

```bibtex

```

### 16.4 Get Project Files

```http
GET /api/projects/{project_id}/files
```

Response:

```json
{
  "files": [
    {"id": "uuid", "path": "main.tex", "version": 1, "content": "..."},
    {"id": "uuid", "path": "references.bib", "version": 1, "content": ""}
  ]
}
```

### 16.5 Update File

```http
PUT /api/projects/{project_id}/files/{file_id}
```

Request:

```json
{
  "content": "...",
  "base_version": 1
}
```

If `base_version` is stale, return `409 Conflict`.

### 16.6 Search Papers

```http
POST /api/papers/search
```

Request:

```json
{
  "query": "graph retrieval augmented generation scientific literature",
  "source": "openalex",
  "limit": 10
}
```

Response:

```json
{
  "results": [
    {
      "external_id": "https://openalex.org/W...",
      "title": "...",
      "year": 2024,
      "authors": ["..."],
      "abstract": "...",
      "cited_by_count": 42,
      "doi": "...",
      "imported": false
    }
  ]
}
```

### 16.7 Import Paper

```http
POST /api/papers/import
```

Request:

```json
{
  "project_id": "uuid",
  "source": "openalex",
  "source_id": "https://openalex.org/W..."
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

### 16.8 Agent Stream

```http
POST /api/agent/stream
```

Request:

```json
{
  "project_id": "uuid",
  "session_id": "uuid-or-null",
  "message": "Suggest citations for the introduction paragraph.",
  "active_file_path": "main.tex",
  "selected_text": "..."
}
```

Response should stream events:

```text
event: message_delta
data: {"text": "I will look for papers..."}

event: tool_call
data: {"tool_name": "retrieve_evidence", "arguments": {...}}

event: tool_result
data: {"tool_name": "retrieve_evidence", "summary": "Found 8 candidate papers."}

event: citation_suggestions
data: {"recommendations": [...]}

event: done
data: {"session_id": "uuid"}
```

---

## 17. Frontend UX Design

### 17.1 Main Workspace Layout

Use a three-pane layout:

```text
+----------------------------------------------------------------+
| Top bar: Project name | Compile | Import Paper | Settings       |
+----------------------+-------------------------+---------------+
| File tree            | LaTeX editor            | AI Agent      |
|                      |                         |               |
| main.tex             | \section{Intro}         | Chat messages |
| references.bib       | ...                     | Tool traces   |
|                      |                         | Citations     |
+----------------------+-------------------------+---------------+
| Optional bottom/right panel: PDF preview / citation graph       |
+----------------------------------------------------------------+
```

For MVP, use resizable panels:

- Left: file tree.
- Middle: editor.
- Right: agent.
- Bottom drawer: PDF preview or graph.

### 17.2 Essential Components

#### LatexEditor.tsx

Responsibilities:

- Render CodeMirror editor.
- Track unsaved changes.
- Save file on debounce or Cmd+S.
- Expose selected text to agent panel.
- Provide insert citation action.

#### AgentPanel.tsx

Responsibilities:

- Chat input.
- Streaming responses.
- Tool trace display.
- Citation suggestion cards.
- Patch review cards.

#### CitationSuggestionCard.tsx

Show:

- Title.
- Authors/year.
- Reason to cite.
- Evidence snippet.
- Buttons:
  - Import paper.
  - Insert `\cite{key}`.
  - Add BibTeX.
  - Show graph neighborhood.

#### CitationGraph.tsx

Show:

- Paper nodes.
- Citation edges.
- Highlight seed paper.
- Highlight recommended papers.
- Click node to see metadata.

Use `@xyflow/react` first. Later, switch to Sigma.js if graph size grows.

### 17.3 Agent Tool Trace UI

Render something like:

```text
Tool trace
✓ inspect_latex_project: read main.tex and references.bib
✓ retrieve_evidence: found 12 relevant chunks
✓ get_citation_neighborhood: expanded 2-hop graph around 4 papers
✓ rank_related_work: ranked 8 candidate citations
```

This matters for interviews because it shows that the agent is tool-driven and observable.

---

## 18. LaTeX Editing and Patching

### 18.1 Patch Principles

The agent should not silently overwrite files. Use this flow:

1. Agent proposes a patch.
2. UI shows before/after or diff.
3. User accepts or rejects.
4. Backend applies patch only if file version matches.
5. Backend stores new file version.

### 18.2 Structured Patch Model

Prefer this for MVP:

```python
class ReplaceRangePatch(BaseModel):
    operation: Literal["replace_range"]
    path: str
    base_version: int
    start_offset: int
    end_offset: int
    new_text: str
```

Later support unified diffs.

### 18.3 Citation Insertion

When user accepts citation suggestion:

1. Add `\cite{bibtex_key}` at cursor or selected range.
2. Add BibTeX to `references.bib` if missing.
3. Add row to `project_papers`.
4. Save file versions.

### 18.4 BibTeX Key Generation

Format:

```text
firstauthorYYYYfirsttitleword
```

Example:

```text
lewis2020retrieval
```

Collision handling:

```text
lewis2020retrieval
lewis2020retrievala
lewis2020retrievalb
```

---

## 19. LaTeX Compilation Security

LaTeX compilation can be dangerous if unrestricted. For MVP:

1. Compile inside a restricted container or worker process.
2. Use a temporary project directory.
3. Copy only project files into that directory.
4. Run Tectonic with timeout.
5. Disable shell escape.
6. Limit output file size.
7. Capture logs.
8. Delete temp files after compile or keep only PDF/log artifact.

Example command:

```bash
tectonic main.tex --outdir /tmp/citepilot-latex/<compilation_id>
```

Python shape:

```python
async def compile_project(project_id: UUID, main_file_path: str) -> CompilationResult:
    files = await load_project_files(project_id)
    workdir = create_temp_workdir(project_id)
    write_files_safely(workdir, files)
    result = await run_with_timeout(
        ["tectonic", main_file_path, "--outdir", output_dir],
        cwd=workdir,
        timeout=settings.LATEX_COMPILE_TIMEOUT_SECONDS,
    )
    return parse_compilation_result(result)
```

Path safety:

- Reject absolute paths.
- Reject `..` segments.
- Reject hidden system paths.
- Only allow project-relative paths.

---

## 20. Retrieval and Generation Prompts

### 20.1 Related Work Prompt

System prompt:

```text
You are CitePilot, a research-writing assistant. You help users write LaTeX research papers using retrieved scholarly evidence.

Rules:
- Use only the evidence provided by tools for factual claims.
- Do not invent citations.
- When recommending citations, explain why each paper is relevant.
- Distinguish between foundational papers, recent papers, and directly related papers.
- If evidence is weak, say so.
- Prefer concise, useful responses.
- When editing LaTeX, preserve the user's style and avoid unnecessary rewrites.
```

User context template:

```text
Project: {project_name}
Active file: {active_file_path}
Selected text:
{selected_text}

User request:
{message}
```

Tool evidence template:

```text
Retrieved evidence:
{evidence_json}

Citation neighborhood summary:
{graph_summary_json}
```

Output format:

```json
{
  "answer": "...",
  "citation_recommendations": [
    {
      "paper_id": "...",
      "bibtex_key": "...",
      "reason": "...",
      "suggested_sentence": "..."
    }
  ],
  "latex_patch": null
}
```

### 20.2 Research Gap Prompt

```text
You are analyzing a local scientific citation graph. Your job is to suggest plausible research gaps based only on the provided graph neighborhood and paper summaries.

For each gap:
- State the gap clearly.
- Explain which papers support the gap.
- Explain why the gap may matter.
- Do not claim novelty unless the evidence strongly supports it.
- Label confidence as low, medium, or high.
```

### 20.3 LaTeX Patch Prompt

```text
You are editing a LaTeX document. Return only a structured patch. Do not rewrite unrelated sections. Preserve existing commands and citations. If adding citations, use only provided BibTeX keys.
```

---

## 21. GraphRAG Implementation Details

### 21.1 Why GraphRAG Here

Plain RAG asks:

```text
Which chunks are semantically similar to my query?
```

GraphRAG asks:

```text
Which papers are relevant through semantic similarity, citation relationships, author networks, shared concepts, methods, and datasets?
```

This is the main technical thesis of the project.

### 21.2 Retrieval Pipeline

Implement in `backend/app/retrieval/hybrid.py`:

```python
class HybridRetriever:
    async def retrieve(
        self,
        project_id: UUID,
        query: str,
        seed_paper_ids: list[UUID] | None = None,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        query_embedding = await self.embedding_client.embed_text(query)
        vector_results = await self.vector_store.search(query_embedding, limit=30)

        seed_ids = seed_paper_ids or [r.paper_id for r in vector_results[:5]]
        graph_candidates = await self.graph_search.expand(seed_ids, depth=2, limit=80)

        merged = self.merge_candidates(vector_results, graph_candidates)
        scored = self.score_candidates(merged, query=query, project_id=project_id)
        return scored[:limit]
```

### 21.3 Graph Candidate Features

For each candidate paper, compute:

```text
min_graph_distance
is_cited_by_seed
is_reference_of_seed
shared_reference_count
co_citation_count
shared_concept_count
citation_count_log
publication_year
already_in_project
```

### 21.4 Explanation Generation

For each recommendation, generate a reason from features:

```text
Recommended because it is one hop from the seed paper, shares concepts {GraphRAG, citation graph}, and has high semantic similarity to your paragraph.
```

Do not only produce a black-box score.

---

## 22. Graph Visualization Data Contract

Endpoint:

```http
GET /api/graph/neighborhood?paper_id=...&depth=2
```

Response:

```json
{
  "nodes": [
    {
      "id": "uuid",
      "type": "paper",
      "label": "Paper title shortened",
      "title": "Full paper title",
      "year": 2024,
      "cited_by_count": 123,
      "is_seed": true
    }
  ],
  "edges": [
    {
      "id": "source-target-CITES",
      "source": "uuid",
      "target": "uuid",
      "type": "CITES"
    }
  ]
}
```

For `@xyflow/react`, convert to:

```ts
type GraphNode = {
  id: string;
  position: { x: number; y: number };
  data: {
    label: string;
    title: string;
    year?: number;
    citedByCount?: number;
  };
};
```

Use a simple radial layout first:

- Seed paper in center.
- Cited papers on left.
- Citing papers on right.
- Shared-concept papers below.

Later, add force-directed layout.

---

## 23. Implementation Milestones

## Milestone 0: Bootstrap Repository

### Tasks

- Create monorepo structure.
- Add Docker Compose.
- Add `.env.example`.
- Add backend Dockerfile.
- Add web Dockerfile.
- Add Makefile.

### Makefile

```makefile
up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

backend-shell:
	docker compose exec backend bash

web-shell:
	docker compose exec web sh

migrate:
	docker compose exec backend alembic upgrade head

test-backend:
	docker compose exec backend pytest
```

### Acceptance Criteria

- `docker compose up --build` starts Postgres, Neo4j, Redis, backend, worker, and frontend.
- `GET http://localhost:8000/api/health` returns status ok.
- `http://localhost:3000` renders a placeholder CitePilot page.

---

## Milestone 1: Backend Foundation

### Tasks

- Create FastAPI app.
- Add config loading.
- Add DB connection.
- Add Neo4j connection.
- Add Redis connection.
- Add health endpoint.
- Add JSON logging.

### Acceptance Criteria

- Health endpoint checks all services.
- Tests pass for health endpoint.
- Invalid DB connection returns useful error in logs.

---

## Milestone 2: Postgres Models and Migrations

### Tasks

- Add SQLAlchemy models.
- Add Alembic migrations.
- Create dev user seed.
- Add project CRUD.
- Add project file CRUD.

### Acceptance Criteria

- User can create a project.
- Project automatically gets `main.tex` and `references.bib`.
- User can update a file.
- File version increments.
- Stale file update returns conflict.

---

## Milestone 3: Frontend Workspace

### Tasks

- Create project list page.
- Create project workspace page.
- Add file tree.
- Add CodeMirror LaTeX editor.
- Add save functionality.
- Add right-side AI panel placeholder.
- Add PDF preview placeholder.

### Acceptance Criteria

- User can open project.
- User can edit `main.tex`.
- Cmd+S or Save button persists file.
- Refresh keeps saved content.

---

## Milestone 4: OpenAlex Search and Import

### Tasks

- Implement OpenAlex client.
- Implement search endpoint.
- Implement normalization.
- Implement import job.
- Store papers/authors/concepts/references in Postgres.
- Create initial paper chunks.

### Acceptance Criteria

- User can search OpenAlex from UI.
- User can import a paper.
- Paper appears in project citation list.
- Imported paper data is visible in Postgres.
- Import uses fixture in tests.

---

## Milestone 5: Neo4j Graph Sync

### Tasks

- Add Neo4j schema constraints.
- Add graph sync function for paper imports.
- Merge paper nodes.
- Merge author nodes.
- Merge concept nodes.
- Merge citation edges.
- Add graph neighborhood endpoint.

### Acceptance Criteria

- Imported paper appears as `Paper` node.
- Authors appear as `Author` nodes.
- Concepts appear as `Concept` nodes.
- Citation edges appear when referenced papers are imported or stubbed.
- Graph neighborhood endpoint returns nodes/edges.

---

## Milestone 6: Embeddings and Vector Search

### Tasks

- Add embedding client interface.
- Add one embedding provider implementation.
- Add `paper_chunks.embedding` storage.
- Add vector search endpoint.
- Add tests with fake embedding client.

### Acceptance Criteria

- Imported paper chunks get embeddings.
- Vector search returns relevant chunks.
- Tests do not call external embedding API.

---

## Milestone 7: Hybrid GraphRAG Retrieval

### Tasks

- Implement vector retrieval.
- Implement graph expansion retrieval.
- Implement candidate merge.
- Implement scoring.
- Implement explanation fields.
- Add `retrieve_evidence` internal tool.

### Acceptance Criteria

- Given a paragraph, system returns ranked evidence.
- Each result includes score and explanation.
- Results include both vector and graph-derived candidates.

---

## Milestone 8: Agent Endpoint

### Tasks

- Create agent session tables.
- Implement streaming endpoint.
- Implement intent classifier.
- Implement tool call loop.
- Implement related work/citation suggestion response.
- Log tool calls.

### Acceptance Criteria

- User can ask for citations for selected text.
- Agent calls `retrieve_evidence` and `rank_related_work`.
- UI shows streamed response.
- UI shows tool trace.
- Suggestions include paper title, reason, evidence, and BibTeX key.

---

## Milestone 9: BibTeX and Citation Insertion

### Tasks

- Implement BibTeX generation.
- Add `project_papers` table logic.
- Add insert citation action in frontend.
- Add BibTeX append to `references.bib`.

### Acceptance Criteria

- Clicking “Insert citation” inserts `\cite{key}` into `main.tex`.
- `references.bib` gets the correct BibTeX entry.
- Duplicate BibTeX entries are not added.

---

## Milestone 10: LaTeX Compilation

### Tasks

- Add Tectonic to worker image.
- Implement compile job.
- Add compile endpoint.
- Store compilation logs.
- Serve PDF artifact.
- Show PDF preview in frontend.

### Acceptance Criteria

- User clicks Compile.
- Worker compiles LaTeX.
- UI shows logs if compile fails.
- UI shows PDF if compile succeeds.

---

## Milestone 11: MCP Server

### Tasks

- Add MCP Python SDK.
- Create MCP server.
- Register core tools.
- Add README section for running MCP server.
- Test with MCP inspector or compatible client.

### Acceptance Criteria

- MCP server starts locally.
- Agent client can call `search_papers`.
- Agent client can call `get_citation_neighborhood`.
- Agent client can call `retrieve_evidence`.
- MCP tools reuse backend core logic.

---

## Milestone 12: Interview Polish

### Tasks

- Add architecture diagram to README.
- Add demo GIF or screenshots.
- Add seeded demo project.
- Add sample imported papers.
- Add tool trace screenshot.
- Add graph visualization screenshot.
- Add resume bullet.
- Add “System Design Notes” section.

### Acceptance Criteria

- A reviewer can run the project with Docker Compose.
- README clearly explains GraphRAG pipeline.
- Demo works in under 3 minutes.
- You can explain every major design choice.

---

## 24. Testing Strategy

### 24.1 Backend Tests

Use pytest.

Test categories:

```text
unit tests:
  - OpenAlex abstract reconstruction
  - normalization
  - BibTeX key generation
  - hybrid score calculation
  - patch application
  - path sanitization

integration tests:
  - project creation
  - paper import with fixture
  - vector search with fake embeddings
  - graph sync with test Neo4j if available
  - agent tool registry
```

### 24.2 Frontend Tests

Optional for MVP, but add if time:

- Component test for CitationSuggestionCard.
- Component test for FileTree.
- Basic Playwright flow:
  - create project
  - edit file
  - save
  - search/import paper

### 24.3 Mocking External APIs

Never call external APIs in tests.

Use fixtures:

```text
backend/app/tests/fixtures/openalex_work.json
backend/app/tests/fixtures/openalex_search.json
backend/app/tests/fixtures/semantic_scholar_paper.json
```

---

## 25. Observability and Logging

### 25.1 Log These Events

- Paper search.
- Paper import job started/completed/failed.
- Embedding job started/completed/failed.
- Graph sync started/completed/failed.
- Agent session created.
- Tool call started/completed/failed.
- LaTeX compilation started/completed/failed.

### 25.2 Tool Call Logging

Every tool call should write to `tool_calls`:

```json
{
  "tool_name": "retrieve_evidence",
  "arguments": {
    "project_id": "...",
    "query": "..."
  },
  "status": "completed",
  "result": {
    "summary": "Found 10 evidence chunks"
  }
}
```

Do not store giant raw LLM responses in logs unless needed.

---

## 26. Security and Safety

### 26.1 External API Safety

- Rate limit external API calls.
- Use retries with exponential backoff.
- Cache search results if possible.
- Include `mailto` when API etiquette recommends it.

### 26.2 LaTeX Safety

- No shell escape.
- Restricted workdir.
- Timeout.
- File path sanitization.
- No arbitrary file access.

### 26.3 Agent Safety

The agent must not have tools for:

- arbitrary shell commands
- arbitrary SQL
- arbitrary Cypher
- unrestricted filesystem reads
- unrestricted filesystem writes

All tools should be narrow and typed.

### 26.4 Data Boundary Safety

Every project-level tool must require `project_id` and verify access.

For MVP, access can be simplified to the dev user, but keep the function signature ready for real users.

---

## 27. README Demo Script

Use this exact demo story:

1. Open CitePilot.
2. Create project: “GraphRAG Literature Review.”
3. Show `main.tex` in editor.
4. Search: “graph retrieval augmented generation scientific literature.”
5. Import 3 papers.
6. Open graph panel and show citation/concept relationships.
7. Highlight paragraph in introduction.
8. Ask agent: “Suggest related work citations for this paragraph.”
9. Show tool trace:
   - `inspect_latex_project`
   - `retrieve_evidence`
   - `get_citation_neighborhood`
   - `rank_related_work`
10. Show citation cards.
11. Insert one citation.
12. Show `references.bib` updated.
13. Compile PDF.
14. Explain architecture.

---

## 28. Resume Bullets

Use one of these:

```text
Built CitePilot, an agentic research-writing platform combining a browser-based LaTeX editor with citation-aware GraphRAG over scientific papers using React, TypeScript, FastAPI, Postgres/pgvector, Neo4j, Redis, and MCP tools.
```

```text
Implemented a scientific knowledge graph over papers, authors, venues, concepts, and citation edges, then combined graph traversal with vector retrieval to recommend citations and generate grounded related-work drafts.
```

```text
Exposed research retrieval, citation-neighborhood expansion, BibTeX generation, and LaTeX patching as typed MCP tools for an AI agent, with observable tool traces and versioned document edits.
```

---

## 29. Interview Explanation

Say this:

```text
I built CitePilot because I wanted to go beyond a normal RAG chatbot. In research writing, the structure between papers matters as much as the text. So I modeled papers, citations, authors, venues, and concepts as a graph in Neo4j, stored chunks and embeddings in Postgres with pgvector, and built a hybrid retriever that combines semantic similarity with graph expansion.

The frontend is a React/TypeScript LaTeX workspace. The backend is FastAPI with Postgres, Neo4j, Redis, and background workers. The agent does not just answer from a prompt; it calls typed tools to search papers, inspect the LaTeX project, expand citation neighborhoods, retrieve evidence, generate BibTeX, and propose safe document patches. I also exposed those tools through MCP so the same capabilities can be used by an external agent runtime.
```

If asked why not just use a vector database:

```text
Vector search is good for semantic similarity, but it misses explicit scholarly structure. Citation edges, co-citation, bibliographic coupling, shared methods, and shared datasets provide signals that embeddings alone may not capture. The hybrid design lets the system retrieve papers that are textually relevant and structurally important.
```

If asked why both Postgres and Neo4j:

```text
Postgres is my durable application and vector store. Neo4j is my graph traversal layer. I could store edges in Postgres, but Cypher makes graph neighborhood queries and relationship-heavy retrieval much easier to implement and explain.
```

If asked what was hard:

```text
The hardest part was making the agent reliable. I had to keep tools narrow, typed, and observable. Instead of giving the model arbitrary database access, I exposed specific tools like retrieve_evidence and get_citation_neighborhood. That made the system safer and easier to debug.
```

---

## 30. Future Extensions

After MVP:

1. **Full-text PDF ingestion**
   - Parse arXiv PDFs.
   - Use GROBID for scholarly PDF structure.
   - Extract sections, figures, tables, and inline citations.

2. **Claim graph**
   - Extract claims from papers.
   - Link claims to supporting/opposing papers.

3. **Method/dataset extraction**
   - Use LLM extraction with validation.
   - Build `USES_METHOD` and `EVALUATES_ON` edges.

4. **Research gap engine**
   - Detect underexplored combinations of method/task/dataset.
   - Use graph community detection.

5. **Collaborative editing**
   - Add Yjs/CRDT.
   - Real-time multi-user editor.

6. **Kubernetes deployment**
   - Deploy frontend, backend, worker, Redis, Postgres, Neo4j.
   - Add CI/CD.

7. **Agent evaluation harness**
   - Test citation suggestions against known related-work sections.
   - Measure citation precision.
   - Track hallucinated citation rate.

8. **MCP external client support**
   - Use the CitePilot MCP server from Claude Desktop, Cursor, or another MCP-compatible client.

---

## 31. First Week Build Plan

### Day 1

- Bootstrap repo.
- Docker Compose.
- FastAPI health.
- Next.js placeholder.
- Postgres/Neo4j/Redis running.

### Day 2

- Project CRUD.
- File CRUD.
- LaTeX editor UI.
- Save file.

### Day 3

- OpenAlex search.
- Import paper job.
- Store papers/authors/concepts.

### Day 4

- Neo4j graph sync.
- Graph neighborhood endpoint.
- Graph visualization UI.

### Day 5

- Embeddings.
- Vector search.
- Hybrid retrieval.

### Day 6

- Agent streaming endpoint.
- Tool trace UI.
- Citation recommendation cards.

### Day 7

- BibTeX insertion.
- Tectonic compile.
- MCP server.
- README/demo polish.

---

## 32. Definition of Done

The project is successful when:

- It runs locally with Docker Compose.
- User can write LaTeX.
- User can import scientific papers.
- Papers are stored in Postgres.
- Citation/concept graph is stored in Neo4j.
- Chunks are embedded in pgvector.
- Agent can recommend citations from hybrid retrieval.
- Agent tool calls are visible.
- User can insert citation and BibTeX.
- User can compile a PDF.
- MCP server exposes at least 5 useful tools.
- README explains architecture clearly.

---

## 33. Minimal End-to-End Acceptance Test

A coding agent should verify this before calling the MVP complete:

```text
1. Run docker compose up --build.
2. Open localhost:3000.
3. Create project.
4. Edit main.tex and save.
5. Search OpenAlex for "GraphRAG".
6. Import one paper.
7. Confirm Postgres has paper row.
8. Confirm Neo4j has Paper node.
9. Confirm paper_chunks has embeddings or fake embeddings in dev mode.
10. Select intro paragraph.
11. Ask agent for citation suggestions.
12. Confirm tool trace appears.
13. Insert citation.
14. Confirm references.bib updated.
15. Compile PDF.
16. Confirm PDF preview appears or logs show useful error.
17. Start MCP server.
18. Call search_papers and get_citation_neighborhood through MCP.
```

---

## 34. Final Notes for the Coding Agent

Build the system in this order:

```text
runnable app
  -> durable project files
  -> paper ingestion
  -> graph sync
  -> vector retrieval
  -> hybrid retrieval
  -> agent tool loop
  -> citation insertion
  -> LaTeX compilation
  -> MCP exposure
  -> polish
```

Do not start with the agent. The agent is only useful once the tools work.

Do not start with a fancy UI. The UI is only useful once projects, files, papers, and retrieval work.

Do not overbuild authentication. Use a dev user first.

Do not overbuild PDF parsing. Use metadata and abstracts first.

The core technical story is:

```text
CitePilot turns scientific literature into a graph-augmented retrieval layer and exposes that layer to an AI writing agent through typed tools.
```

That is the sentence the whole implementation should support.
