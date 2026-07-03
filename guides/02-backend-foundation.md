# Guide 02 — Backend Foundation (Milestone 1)

[← Bootstrap](01-bootstrap-and-docker.md) | [Roadmap](00-ROADMAP.md) | [Next: Database & Versioning →](03-database-and-file-versioning.md)

**What exists when you finish:** a properly structured FastAPI app — env-driven settings, structured JSON logging, one shared async client per store (Postgres engine, Neo4j driver, Redis) created at startup and disposed at shutdown, CORS configured, a health endpoint that reports *real* per-service connectivity, and a passing test suite.

**Effort:** ~180 lines typed, ~60 pasted. Most files in this guide are ⌨️ TYPE — this is where you learn the FastAPI patterns everything else sits on.

---

## 1. Concepts in this guide

- **12-factor config.** `pydantic-settings` reads typed settings from the environment. Code never reads `os.environ` directly; it asks `Settings`. Typos in env vars become validation errors at boot, not `None` surprises at 2am.
- **The lifespan pattern.** Database engines, drivers, and Redis clients are expensive and hold connection pools. You create them **once** at app startup, stash them on `app.state`, and dispose them at shutdown. Per-request work borrows from the pool. This is the single most important FastAPI production pattern.
- **Dependency injection.** Route handlers declare what they need (`session = Depends(get_db)`); FastAPI resolves it per-request. Handlers stay testable and free of global imports.
- **Structured logging.** `structlog` emits one JSON object per event with stable event names (`app.startup`, `health.postgres_failed`). Grep-able, machine-parsable, and what log aggregators expect. Never `print()`.
- **CORS on day one.** Next.js on `:3000` calling FastAPI on `:8000` is cross-origin. Without the middleware, your first browser fetch fails with an opaque error.

---

## 2. Implementation

### 2.1 `backend/app/config.py` ⌨️ TYPE

Field names match `.env.example` exactly — pydantic-settings maps env vars to fields case-insensitively.

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    APP_NAME: str = "CitePilot"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    # Stores
    DATABASE_URL: str = "postgresql+asyncpg://citepilot:citepilot@postgres:5432/citepilot"
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "citepilot-password"
    REDIS_URL: str = "redis://redis:6379/0"

    # External scholarly APIs
    OPENALEX_MAILTO: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    CROSSREF_MAILTO: str = ""

    # LLM
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""

    # Embeddings
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_DIM: int = 1536

    # LaTeX
    LATEX_WORKDIR: str = "/tmp/citepilot-latex"
    LATEX_COMPILE_TIMEOUT_SECONDS: int = 30

    # Dev auth
    DEV_USER_ID: str = "00000000-0000-0000-0000-000000000001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Why it's written this way:

- `@lru_cache` makes `get_settings()` a singleton — the env is parsed once, and every caller shares the instance.
- `extra="ignore"` lets `.env` contain vars the backend doesn't model (e.g. `POSTGRES_DB`, which only compose consumes).
- Defaults point at the *compose* hostnames, so in-container "it just works"; anything secret defaults to empty and fails loudly where required (the OpenAlex client will enforce `OPENALEX_MAILTO` in Guide 05).

### 2.2 `backend/app/logging.py` 📋 PASTE

```python
import logging
import sys

import structlog


def configure_logging() -> None:
    """Route stdlib logging to stdout and configure structlog for JSON output."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
```

Two things to know:

- **File-name gotcha:** naming this module `app/logging.py` is safe because Python 3 imports are absolute — `import logging` inside the package still resolves to the stdlib. Only `from app import logging` would get ours.
- **Convention from here on:** log events are dot-namespaced verbs, `subsystem.action[.outcome]` — `paper.import.started`, `agent.tool.failed`. Fields, not f-strings: `log.info("paper.import.started", paper_id=..., project_id=...)`. This convention is specified in the blueprint (§18) and you'll use it in every later guide.

### 2.3 `backend/app/db/postgres.py` ⌨️ TYPE

```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- `pool_pre_ping=True` — the pool tests a connection before handing it out, so the app self-heals after a Postgres restart instead of serving one wave of `ConnectionDoesNotExistError`.
- `expire_on_commit=False` — by default SQLAlchemy expires ORM objects on commit, so touching them afterwards triggers a lazy refresh — which **fails under asyncio** ("greenlet" errors). With async sessions you almost always want this off; you'll return committed objects from route handlers constantly.

### 2.4 `backend/app/graph/neo4j_client.py` ⌨️ TYPE

```python
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings


def create_neo4j_driver(settings: Settings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
```

The driver is the pool — one per process, thread/task-safe, sessions are borrowed per unit of work. Same lifecycle philosophy as the SQLAlchemy engine.

### 2.5 `backend/app/graph/schema.py` 📋 PASTE

Constraints are applied idempotently at every startup (`IF NOT EXISTS` makes re-runs free). Uniqueness constraints also create indexes — `MERGE` on `Paper {id}` in Guide 06 would be a full-graph scan without them.

```python
"""Neo4j constraints and indexes, applied idempotently at startup.

Mirrored in infra/scripts/init_neo4j.cypher for manual use in the Neo4j browser.
"""

from neo4j import AsyncDriver

CONSTRAINT_STATEMENTS = [
    "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE",
    "CREATE CONSTRAINT author_id_unique IF NOT EXISTS "
    "FOR (a:Author) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT concept_name_unique IF NOT EXISTS "
    "FOR (c:Concept) REQUIRE c.name IS UNIQUE",
    "CREATE INDEX paper_year_index IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    "CREATE INDEX paper_stub_index IF NOT EXISTS FOR (p:Paper) ON (p.is_stub)",
]


async def apply_constraints(driver: AsyncDriver) -> None:
    async with driver.session() as session:
        for statement in CONSTRAINT_STATEMENTS:
            await session.run(statement)
```

Also create `infra/scripts/init_neo4j.cypher` 📋 with the same six statements, each terminated by `;` — handy for pasting into the Neo4j browser.

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

### 2.6 `backend/app/deps.py` ⌨️ TYPE

The bridge between `app.state` (owned by lifespan) and route handlers (which use `Depends`).

```python
from collections.abc import AsyncIterator

from fastapi import Request
from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_neo4j(request: Request) -> AsyncDriver:
    return request.app.state.neo4j


def get_redis(request: Request) -> Redis:
    return request.app.state.redis
```

`get_db` is a *generator* dependency: FastAPI opens the session before the handler runs and the `async with` closes it after the response — one session per request, always returned to the pool, even on exceptions.

### 2.7 `backend/app/api/routes/health.py` ⌨️ TYPE

A health check that returns a hardcoded `"ok"` is a lie. This one exercises each store with the cheapest possible real query.

```python
from fastapi import APIRouter, Request
from sqlalchemy import text

from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.get("/health")
async def health(request: Request) -> dict:
    checks: dict[str, str] = {}

    try:
        async with request.app.state.db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        log.warning("health.postgres_failed", error=str(exc))
        checks["postgres"] = "error"

    try:
        await request.app.state.neo4j.execute_query("RETURN 1")
        checks["neo4j"] = "ok"
    except Exception as exc:
        log.warning("health.neo4j_failed", error=str(exc))
        checks["neo4j"] = "error"

    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        log.warning("health.redis_failed", error=str(exc))
        checks["redis"] = "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, **checks}
```

Design choice: always HTTP 200, with `status: degraded` in the body. Load balancers that only look at status codes would want a 503 variant — fine to mention in an interview, unnecessary for MVP.

### 2.8 `backend/app/api/router.py` ⌨️ TYPE

One place where all route modules are mounted. Grows in every backend guide.

```python
from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
```

### 2.9 `backend/app/main.py` ⌨️ TYPE — **replace the entire M0 stub**

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.db.postgres import create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver
from app.graph.schema import apply_constraints
from app.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    log = get_logger(__name__)

    app.state.settings = settings
    app.state.db_engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.db_engine)
    app.state.neo4j = create_neo4j_driver(settings)
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    await apply_constraints(app.state.neo4j)
    log.info("app.startup", env=settings.APP_ENV)

    yield

    await app.state.redis.aclose()
    await app.state.neo4j.close()
    await app.state.db_engine.dispose()
    log.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
```

Why an **app factory** (`create_app()`) instead of building at module import: tests construct their own isolated app instance, and nothing runs as an import side effect. The module-level `app = create_app()` at the bottom is what uvicorn's `app.main:app` target points at.

Everything before `yield` is startup; everything after is shutdown, in reverse-acquisition order. Compose healthchecks guarantee the stores are up before this runs, so `apply_constraints` can safely run unconditionally.

### 2.10 `backend/app/tests/conftest.py` 📋 PASTE

```python
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
```

`httpx.ASGITransport` calls the app **in-process** — requests never touch the network. `LifespanManager` is needed because plain ASGI transport skips startup/shutdown, and without it `app.state` would be empty. (`asyncio_mode = "auto"` in `pyproject.toml` is why async fixtures/tests need no decorators.)

### 2.11 `backend/app/tests/test_health.py` 📋 PASTE

```python
async def test_health_reports_all_services(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["neo4j"] == "ok"
    assert body["redis"] == "ok"
```

This is an *integration* test — it runs inside the backend container against the real compose services (that's what `make test-backend` does). Unit tests with fakes start in Guide 05.

---

## 3. Run & verify (acceptance criteria)

Containers auto-reload on save. Then:

1. `curl http://localhost:8000/api/health` → `{"status":"ok","postgres":"ok","neo4j":"ok","redis":"ok"}`.
2. `make test-backend` → 1 passed.
3. **Kill a store and watch health tell the truth:**
   ```bash
   docker compose stop postgres
   curl http://localhost:8000/api/health   # → "status":"degraded","postgres":"error"
   docker compose start postgres
   curl http://localhost:8000/api/health   # → back to "ok" (pool_pre_ping self-heals)
   ```
4. `docker compose logs backend | grep app.startup` → one JSON log line with `"env": "development"`.
5. In the Neo4j browser (`:7474`) run `SHOW CONSTRAINTS` → the four constraints exist.

## 4. Commit checkpoint

```bash
git add -A && git commit -m "M1: backend foundation - settings, structlog, store clients, lifespan, real health checks"
```

## 5. Interview notes

- The lifespan pattern is the answer to "how do you manage database connections in an async web app?" — one pool per process created at startup, per-request sessions borrowed via DI, disposed at shutdown.
- `expire_on_commit=False` and `pool_pre_ping` are the kind of details that show you've actually run async SQLAlchemy, not just read a tutorial.
- Health endpoints should *exercise* dependencies, not return constants — and you demonstrated failure behavior (step 3 above) rather than assuming it.

## 6. Self-test

1. Why must the Neo4j driver / SQLAlchemy engine be created once per process rather than per request?
2. What breaks (and how) if `expire_on_commit` stays `True` with async sessions?
3. Your `.env` sets `EMBEDDING_DIM=abc`. When and how does the app fail?
4. Why does the test fixture need `LifespanManager`?
