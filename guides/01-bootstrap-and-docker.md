# Guide 01 — Bootstrap & Docker (Milestone 0)

[← Roadmap](00-ROADMAP.md) | [Next: Backend Foundation →](02-backend-foundation.md)

**What exists when you finish:** a monorepo where `make up` boots six containers (Postgres+pgvector, Neo4j, Redis, FastAPI backend, arq worker, Next.js frontend), a stub health endpoint answers on `:8000`, and a placeholder page renders on `:3000`.

**Effort:** ~30 lines typed, ~250 lines pasted, plus two scaffold commands. Most of this guide is infrastructure you paste and *read* — the learning here is understanding what each service is for, not memorizing YAML.

---

## 1. Concepts in this guide

- **Why a monorepo:** frontend, backend, and infra evolve together; one `docker compose up` runs everything. Interviewers like "clone → make up → works".
- **Why six services:** Postgres is the durable source of truth (+pgvector for embeddings), Neo4j is a *rebuildable* graph mirror for traversal, Redis backs the job queue and external-API cache, the worker runs slow async jobs (ingestion, compilation) off the request path, and web/backend are the app itself.
- **Healthchecks + `depends_on: condition: service_healthy`:** without them, the backend races the databases on cold start and crashes before Postgres accepts connections. Healthchecks make cold starts deterministic — a small thing that reads as production maturity.
- **Bind mounts + `--reload`:** your host code is mounted into the containers, so edits hot-reload without rebuilding images.

---

## 2. Prerequisites

- Docker Desktop running.
- Node 20+ and pnpm (`npm install -g pnpm` if needed).
- Git.

---

## 3. Create the repo skeleton

The code lives in a `citepilot/` folder next to these guides. 📋 Run:

```bash
cd ~/Desktop/CitePilot
mkdir citepilot && cd citepilot
git init

mkdir -p apps \
  backend/app/api/routes \
  backend/app/db \
  backend/app/graph \
  backend/app/retrieval \
  backend/app/ingestion \
  backend/app/latex \
  backend/app/agent/llm \
  backend/app/mcp_server \
  backend/app/workers \
  backend/app/tests/fixtures \
  infra/docker \
  infra/scripts

# Python packages need __init__.py files
touch backend/app/__init__.py \
  backend/app/api/__init__.py \
  backend/app/api/routes/__init__.py \
  backend/app/db/__init__.py \
  backend/app/graph/__init__.py \
  backend/app/retrieval/__init__.py \
  backend/app/ingestion/__init__.py \
  backend/app/latex/__init__.py \
  backend/app/agent/__init__.py \
  backend/app/agent/llm/__init__.py \
  backend/app/mcp_server/__init__.py \
  backend/app/workers/__init__.py \
  backend/app/tests/__init__.py
```

### 3.1 `.gitignore` 📋 PASTE

```gitignore
# Secrets
.env

# Python
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/

# Node / Next.js
node_modules/
.next/
out/

# OS / editor
.DS_Store
.vscode/
.idea/
```

---

## 4. Environment variables

### 4.1 `.env.example` 📋 PASTE

Every secret and config value comes from the environment (rule: never hardcode). This file is the committed template; the real `.env` is gitignored.

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
OPENALEX_MAILTO=your_email@example.com   # REQUIRED: OpenAlex client refuses to start without it
SEMANTIC_SCHOLAR_API_KEY=                # optional; S2 client no-ops when empty
CROSSREF_MAILTO=your_email@example.com

# LLM
LLM_PROVIDER=anthropic
LLM_MODEL=
LLM_API_KEY=

# Embeddings
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=
EMBEDDING_API_KEY=
EMBEDDING_DIM=1536                       # MUST match paper_chunks.embedding column dim

# LaTeX
LATEX_WORKDIR=/tmp/citepilot-latex
LATEX_COMPILE_TIMEOUT_SECONDS=30

# Dev auth
DEV_USER_ID=00000000-0000-0000-0000-000000000001
```

> Note: `EMBEDDING_API_KEY` is an addition to the spec's env list — the LLM provider (Anthropic) and embedding provider (OpenAI) are different vendors, so they need separate keys.

Then create your real env file:

```bash
cp .env.example .env
# Edit .env: set OPENALEX_MAILTO to your real email.
# LLM/embedding keys can stay empty until Guide 07.
```

**Why hostnames like `postgres:5432`, not `localhost`?** Inside the compose network, each service reaches the others by service name via Docker's internal DNS. `localhost` inside a container is the container itself.

---

## 5. Backend: minimal boot

The backend gets its full foundation in Guide 02. For M0 we need just enough for the container to start and answer a health stub.

### 5.1 `backend/pyproject.toml` 📋 PASTE

All backend dependencies, declared up front so you build the Docker image once. Read the comments — knowing *why* each dependency exists is interview material.

```toml
[project]
name = "citepilot-backend"
version = "0.1.0"
description = "CitePilot backend: FastAPI + GraphRAG over a scientific knowledge graph"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",            # HTTP API framework
    "uvicorn[standard]>=0.30",   # ASGI server
    "pydantic>=2.9",             # typed request/response/tool models
    "pydantic-settings>=2.5",    # env-based configuration
    "sqlalchemy[asyncio]>=2.0.35", # async ORM/core for Postgres
    "asyncpg>=0.29",             # async Postgres driver
    "alembic>=1.13",             # database migrations
    "pgvector>=0.3",             # Vector column type for SQLAlchemy
    "neo4j>=5.24",               # official async Neo4j driver
    "redis>=5.0",                # async Redis client (cache)
    "arq>=0.26",                 # async-native job queue on Redis
    "httpx>=0.27",               # async HTTP client for external APIs
    "tenacity>=9.0",             # retry with exponential backoff
    "structlog>=24.4",           # structured JSON logging
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "asgi-lifespan>=2.1",        # runs FastAPI lifespan inside tests
    "ruff>=0.6",
]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["app/tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

**Why arq and not Celery or RQ?** The whole backend is `async def`. RQ is sync-only and would force sync DB drivers inside jobs; Celery is heavy for an MVP. arq jobs are plain async functions sharing the same clients as the API.

### 5.2 `backend/app/main.py` ⌨️ TYPE (stub — fully replaced in Guide 02)

```python
from fastapi import FastAPI

app = FastAPI(title="CitePilot")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "note": "stub - real checks arrive in guide 02"}
```

### 5.3 `backend/app/workers/arq_app.py` ⌨️ TYPE (upgraded in Guide 05)

The worker container runs `arq app.workers.arq_app.WorkerSettings`. arq discovers jobs from the `functions` list; `ping` is a placeholder proving the queue works.

```python
import os

from arq.connections import RedisSettings


async def ping(ctx: dict) -> str:
    """Placeholder job proving the worker boots and consumes the queue."""
    return "pong"


class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
```

---

## 6. Frontend: scaffold Next.js

Don't type a Next.js app from scratch — scaffold it, then own the files that matter (Guide 04). 📋 Run from `citepilot/`:

```bash
pnpm create next-app@latest apps/web \
  --typescript --tailwind --eslint --app --no-src-dir \
  --import-alias "@/*" --use-pnpm
```

If it prompts for anything else (e.g. Turbopack), accept the default.

Two edits after scaffolding:

**`apps/web/package.json`** — the dev server must bind to `0.0.0.0` so Docker can expose it (inside a container, the default `localhost` bind is unreachable from your Mac):

```json
"scripts": {
  "dev": "next dev -H 0.0.0.0",
  ...
}
```

**`apps/web/app/page.tsx`** ⌨️ TYPE — replace the default page with a placeholder (becomes the project list in Guide 04):

```tsx
export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">CitePilot</h1>
        <p className="mt-2 text-muted-foreground">
          LaTeX editor + GraphRAG research assistant
        </p>
      </div>
    </main>
  );
}
```

---

## 7. Dockerfiles

### 7.1 `infra/docker/backend.Dockerfile` 📋 PASTE

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Why `pip install -e .` (editable)?** The install records a pointer to `/app/backend` instead of copying code into site-packages. Compose then bind-mounts your host `./backend` over that same path, so the container always runs your current code and `--reload` picks up edits. (Tradeoff noted: copying the whole source before installing means dependency layers aren't cached across code changes — fine for a dev image.)

### 7.2 `infra/docker/worker.Dockerfile` 📋 PASTE

Identical base for now; Guide 11 adds Tectonic (the LaTeX engine) with a pre-warmed package bundle to this image only.

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/ ./
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["arq", "app.workers.arq_app.WorkerSettings"]
```

### 7.3 `infra/docker/web.Dockerfile` 📋 PASTE

```dockerfile
FROM node:20-slim

RUN npm install -g pnpm

WORKDIR /app/apps/web

COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web/ ./

EXPOSE 3000
CMD ["pnpm", "dev"]
```

**Layer-caching note:** here we *do* copy `package.json` + lockfile first, so `pnpm install` re-runs only when dependencies change — JS installs are slow enough to care.

---

## 8. `docker-compose.yml` 📋 PASTE (spec section 5, verbatim)

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
    command: pnpm dev

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  latex_artifacts:
```

Things worth understanding before moving on:

- **`- /app/apps/web/node_modules`** (anonymous volume): the bind mount of `./apps/web` would otherwise bury the `node_modules` that was installed *inside* the image with your (empty) host folder. The anonymous volume shields it.
- **`latex_artifacts` shared volume:** the worker writes compiled PDFs there; the backend serves them from the same volume.
- **No `init_postgres.sql`:** the `vector` extension is created inside the first Alembic migration (Guide 03) so it works on fresh *and* existing volumes.

---

## 9. `Makefile` 📋 PASTE

⚠️ Makefile recipe lines must be indented with a **TAB**, not spaces, or you'll get `missing separator`.

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

resync-graph:
	docker compose exec backend python -m app.graph.resync
```

(`migrate` works after Guide 03; `resync-graph` after Guide 06.)

### `README.md` stub ⌨️ TYPE

```markdown
# CitePilot

An Overleaf + Cursor-style research workspace: browser LaTeX editor on the left,
an agentic GraphRAG research assistant on the right, backed by a scientific
knowledge graph (Postgres + pgvector + Neo4j).

## Run

    cp .env.example .env   # set OPENALEX_MAILTO
    make up

- Web: http://localhost:3000
- API: http://localhost:8000/api/health
- Neo4j browser: http://localhost:7474
```

---

## 10. Run & verify (acceptance criteria)

```bash
make up
```

First build takes a few minutes. Then verify **all** of these:

1. `docker compose ps` — six services, the three stores showing `(healthy)`.
2. `curl http://localhost:8000/api/health` → `{"status":"ok",...}`.
3. http://localhost:3000 renders the CitePilot placeholder.
4. http://localhost:7474 → login `neo4j` / `citepilot-password` works.
5. `docker compose logs worker` shows arq started with the `ping` function registered.
6. Kill everything (`make down`), run `make up` again — cold start comes up clean with no race-condition crashes. That's the healthchecks earning their keep.

## 11. Commit checkpoint

```bash
git add -A && git commit -m "M0: monorepo bootstrap - compose, dockerfiles, minimal backend/worker/web"
```

## 12. Interview notes

- "Cold clone to running app is one command" — say it, it lands.
- Know the **one-sentence role of each service** (Section 1 above). The classic follow-up is "why both Postgres and Neo4j?" — Postgres is the source of truth + vector store; Neo4j is a *derived, rebuildable* traversal layer (you'll prove rebuildability in Guide 06 with `resync_graph`).
- Healthcheck-gated `depends_on` is a concrete answer to "what production concerns did you handle?"

## 13. Self-test

1. Why does the web dev server need `-H 0.0.0.0` inside Docker?
2. What happens on cold start if `depends_on` doesn't gate on `service_healthy`?
3. Why is there no `init_postgres.sql` creating the `vector` extension?
4. Why editable (`-e`) pip install in the backend image?
