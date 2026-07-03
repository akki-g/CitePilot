# Module Guide: Foundation and Database

Files in this guide (all complete — type them as-is):

- `backend/app/config.py`
- `backend/app/logging.py`
- `backend/app/db/postgres.py`
- `backend/app/db/models.py`
- `backend/app/deps.py`
- `backend/app/main.py`
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`
- `backend/alembic/versions/0001_initial_schema.py`

Prerequisite: the repo skeleton, `docker-compose.yml`, Dockerfiles, and `pyproject.toml` from [../01-bootstrap-and-docker.md](../01-bootstrap-and-docker.md). This guide supersedes `../02-backend-foundation.md` (same content, plus the DB layer).

**Why this module:** one typed settings object, one engine/driver/pool per process created in the FastAPI lifespan, and a Postgres schema that is the source of truth for everything (Neo4j and pgvector search are derived from these rows).

**How to read the snippets:** the code blocks are still meant to be usable. I added comments inside Python where they help, and added walkthrough notes after blocks where inline comments would make the snippet noisy or invalid.

---

## `backend/app/config.py`

Field names match `.env.example` exactly; pydantic-settings maps env vars case-insensitively. `@lru_cache` = parse env once per process. Typos in env values fail at boot, not at 2am.

```python
# `lru_cache` memoizes a function result. Here it makes settings a process-wide singleton.
from functools import lru_cache

# BaseSettings reads environment variables into a typed Pydantic model.
# SettingsConfigDict controls how pydantic-settings loads `.env` and unknown keys.
from pydantic_settings import BaseSettings, SettingsConfigDict


# One class owns all configuration. Other modules should ask for Settings,
# not call `os.environ` directly, so config access is typed and testable.
class Settings(BaseSettings):
    # env_file=".env" lets local dev read the same values Docker uses.
    # extra="ignore" allows compose-only variables like POSTGRES_DB to live in `.env`.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App identity and URLs. FRONTEND_URL is used by CORS; BACKEND_URL is useful for links.
    APP_ENV: str = "development"
    APP_NAME: str = "CitePilot"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    # Store connection strings. Hostnames are Docker Compose service names, not localhost.
    DATABASE_URL: str = "postgresql+asyncpg://citepilot:citepilot@postgres:5432/citepilot"
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "citepilot-password"
    REDIS_URL: str = "redis://redis:6379/0"

    # Scholarly metadata providers. OpenAlex/Crossref use mailto for polite API behavior.
    OPENALEX_MAILTO: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    CROSSREF_MAILTO: str = ""

    # LLM provider config. The agent code should depend on an adapter, not this provider directly.
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""

    # Embedding config. EMBEDDING_DIM must match the pgvector column dimension exactly.
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_DIM: int = 1536

    # Tectonic writes temp files/artifacts under this worker-visible directory.
    LATEX_WORKDIR: str = "/tmp/citepilot-latex"
    # Hard timeout so a bad LaTeX document cannot hang a worker forever.
    LATEX_COMPILE_TIMEOUT_SECONDS: int = 30

    # MVP auth shortcut: all local actions run as this seeded user.
    DEV_USER_ID: str = "00000000-0000-0000-0000-000000000001"


# `get_settings()` is the only function other modules should import.
# Caching means Pydantic parses environment variables once, not on every request.
@lru_cache
def get_settings() -> Settings:
    # Instantiating Settings performs env loading and type validation.
    return Settings()
```

Walkthrough:

- `Settings` is the app's config contract. If a value matters to the app, it belongs here.
- Defaults point at Docker Compose service hostnames so containers can talk to each other immediately.
- Empty API keys are allowed at boot because later clients decide whether they are required.
- `EMBEDDING_DIM` is intentionally explicit because pgvector columns cannot silently change dimensions.
- `get_settings()` is cached so every import sees the same parsed config object.

## `backend/app/logging.py`

JSON logs on stdout — what Docker and log aggregators expect. Convention for the whole project: event names are stable dotted strings (`paper.import.started`), data goes in fields, never f-strings.

```python
# Standard library logging still exists; structlog builds on top of it.
import logging
# Logs go to stdout because Docker captures stdout/stderr from containers.
import sys

# structlog emits JSON events with stable fields instead of free-form strings.
import structlog


def configure_logging() -> None:
    # Route stdlib logs to stdout as plain messages; structlog formats the JSON.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    # Configure the processors that add context, timestamps, exception info, and JSON rendering.
    structlog.configure(
        processors=[
            # Pulls request/job contextvars into each log event if later code binds them.
            structlog.contextvars.merge_contextvars,
            # Adds `"level": "info"`/`"warning"` etc. to every event.
            structlog.processors.add_log_level,
            # Adds an ISO UTC timestamp so logs can be sorted across containers.
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Includes stack info when explicitly requested.
            structlog.processors.StackInfoRenderer(),
            # Renders exception tracebacks into structured fields.
            structlog.processors.format_exc_info,
            # Final processor: convert the event dict into one JSON string.
            structlog.processors.JSONRenderer(),
        ],
        # Drop events below INFO. In dev you can lower this if debugging noisy internals.
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        # Cache logger wrappers after first use for speed.
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    # Use module names (`__name__`) so logs reveal where an event came from.
    return structlog.get_logger(name)
```

Walkthrough:

- `configure_logging()` should run once at startup before meaningful work begins.
- Every later module should log with `log.info("event.name", field=value)` rather than `print()`.
- JSON logs are grep-friendly locally and machine-readable in production.
- Stable dotted event names make it possible to search for `paper.import.failed` or `agent.tool.started`.

Note: naming this module `app/logging.py` is safe — Python 3 imports are absolute, so `import logging` inside the package still gets the stdlib.

## `backend/app/db/postgres.py`

- `pool_pre_ping` — pool self-heals after a Postgres restart.
- `expire_on_commit=False` — mandatory with async sessions; otherwise touching an ORM object after commit triggers a lazy refresh, which blows up under asyncio ("greenlet" errors).
- `check_embedding_dimension` — the pgvector column dim is frozen at migration time; if `EMBEDDING_DIM` in env disagrees, fail loudly at startup instead of storing garbage vectors. Skips quietly if migrations haven't run yet.

```python
# `text()` lets us run small SQL snippets without defining ORM models for them.
from sqlalchemy import text
# Async SQLAlchemy classes: engine owns the pool, session is the unit of ORM work.
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Settings supplies the DATABASE_URL; this module should not read env vars directly.
from app.config import Settings
# Logger is used by the startup dimension check.
from app.logging import get_logger

# Module-level logger; every event will include this module's name.
log = get_logger(__name__)


def create_engine(settings: Settings) -> AsyncEngine:
    # One engine per process. pool_pre_ping validates connections before use.
    return create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # The factory creates one AsyncSession per request/job.
    # expire_on_commit=False keeps attributes readable after commit in async code.
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_embedding_dimension(engine: AsyncEngine, expected_dim: int) -> None:
    # Open a short-lived connection from the engine pool.
    async with engine.connect() as conn:
        # `to_regclass` returns NULL if the table does not exist yet.
        exists = (await conn.execute(text("SELECT to_regclass('paper_chunks')"))).scalar()
        if exists is None:
            # On a brand-new DB before migrations, warn instead of crashing the app.
            log.warning("db.embedding_dim_check_skipped", reason="paper_chunks missing; run migrations")
            return
        # pgvector stores vector dimension in pg_attribute.atttypmod.
        typmod = (
            await conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'paper_chunks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
    # pgvector encodes dimensions with a small typmod offset.
    actual_dim = typmod - 4  # pgvector stores dim in typmod with a 4-byte header offset
    if actual_dim != expected_dim:
        # Mixed embedding dimensions break vector search, so fail loudly at startup.
        raise RuntimeError(
            f"EMBEDDING_DIM={expected_dim} does not match paper_chunks.embedding vector({actual_dim}). "
            "Change the env var or write a migration; do not mix dimensions."
        )
```

Walkthrough:

- `AsyncEngine` is expensive and owns the connection pool, so it belongs in FastAPI lifespan.
- `AsyncSession` is cheap and short-lived, so each request/job gets its own.
- `pool_pre_ping=True` prevents one wave of failures after Postgres restarts.
- The embedding check protects you from accidentally changing model dimensions without a migration.

## `backend/app/db/models.py`

Matches the blueprint SQL exactly. Three things to notice while typing:

- `metadata` is a reserved attribute on SQLAlchemy declarative classes, so the Python attribute is `paper_metadata`/etc. mapped to a column literally named `"metadata"`.
- `title` on `papers` is nullable — **stub papers** (references we haven't imported yet) have no title.
- The helper functions return a fresh `mapped_column(...)` per call; annotating them as `Mapped[...]` keeps the class bodies terse.

```python
# UUID primary keys make records globally unique without relying on database sequences.
import uuid
# `date` is for publication dates; `datetime` is for created_at/updated_at.
from datetime import date, datetime

# pgvector's SQLAlchemy type for `embedding vector(1536)`.
from pgvector.sqlalchemy import Vector
# SQLAlchemy column/index/constraint building blocks used by the ORM classes below.
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
# PostgreSQL-specific UUID and JSONB column types.
from sqlalchemy.dialects.postgresql import JSONB, UUID
# DeclarativeBase is the root for SQLAlchemy models; Mapped/mapped_column provide typed ORM fields.
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base imported by Alembic env.py."""


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    files: Mapped[list["ProjectFile"]] = relationship(back_populates="project")


class ProjectFile(Base):
    __tablename__ = "project_files"
    __table_args__ = (UniqueConstraint("project_id", "path"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    project: Mapped[Project] = relationship(back_populates="files")


class FileVersion(Base):
    __tablename__ = "file_versions"
    __table_args__ = (UniqueConstraint("file_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False, default="user")  # 'user' | 'agent'
    created_at: Mapped[datetime] = created_at_col()


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(Text, unique=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(Text, unique=True)
    doi: Mapped[str | None] = mapped_column(Text, unique=True)  # ALWAYS normalized before write
    title: Mapped[str | None] = mapped_column(Text)  # nullable: stubs have no title yet
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[date | None] = mapped_column(Date)
    venue_name: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    cited_by_count: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    is_stub: Mapped[bool] = mapped_column(nullable=False, default=False)
    paper_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[uuid.UUID] = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(Text, unique=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    author_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class PaperAuthor(Base):
    __tablename__ = "paper_authors"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    author_order: Mapped[int | None] = mapped_column(Integer)


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (Index("citations_cited_idx", "cited_paper_id"),)  # reverse lookups

    citing_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    cited_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, default="openalex")
    created_at: Mapped[datetime] = created_at_col()


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(Text, nullable=False, default="concept")
    concept_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class PaperConcept(Base):
    __tablename__ = "paper_concepts"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="openalex")


class PaperChunk(Base):
    __tablename__ = "paper_chunks"
    __table_args__ = (UniqueConstraint("paper_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(Text)  # 'title_abstract' for MVP
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))  # dim frozen by migration
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()


class ProjectPaper(Base):
    __tablename__ = "project_papers"
    __table_args__ = (UniqueConstraint("project_id", "bibtex_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    bibtex_key: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[datetime] = created_at_col()


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (Index("agent_messages_session_idx", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' | 'assistant' | 'tool'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE")
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)  # truncated to <= 4 KB before storage
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    queue_job_id: Mapped[str | None] = mapped_column(Text)  # arq job id linkage
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class LatexCompilation(Base):
    __tablename__ = "latex_compilations"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    main_file_path: Mapped[str] = mapped_column(Text, nullable=False, default="main.tex")
    pdf_path: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

> Naming note: the ORM class for the `tool_calls` table is `ToolCallRecord` (not `ToolCall`) because `ToolCall` is the name of the LLM-layer dataclass in `agent/llm/base.py`. Two different things; two different names.

Model walkthrough:

- `Base`: collects table metadata so Alembic can see all ORM tables.
- `uuid_pk()`: avoids repeating the UUID primary-key column definition on every table.
- `created_at_col()` and `updated_at_col()`: standard timestamps; `server_default=func.now()` means Postgres sets the time, not Python.
- `User`: a minimal owner identity for MVP local auth.
- `Project`: a research-writing workspace owned by one user.
- `ProjectFile`: the current content for each file path in a project.
- `FileVersion`: snapshots only explicit saves and agent patches; autosaves update current content without bloating history.
- `Paper`: canonical paper metadata. `is_stub=True` means the paper exists mainly to support citation edges.
- `Author` and `PaperAuthor`: normalized authors plus many-to-many authorship/order.
- `Citation`: directed paper-to-paper edge in Postgres; Neo4j mirrors this for traversal.
- `Concept` and `PaperConcept`: structured topics/methods/datasets later used by graph retrieval.
- `PaperChunk`: text plus pgvector embedding. For MVP it is one `title_abstract` chunk per paper.
- `ProjectPaper`: papers the user has added to a project, with the stable BibTeX key.
- `AgentSession` and `AgentMessage`: conversational state for the in-app agent.
- `ToolCallRecord`: audit log for every tool invocation and result/error.
- `Job`: durable UI-visible status for arq background work.
- `LatexCompilation`: tracks each compile attempt, logs, error, and PDF artifact path.

Column pattern notes:

- `ForeignKey(..., ondelete="CASCADE")` means deleting a parent project/file/paper removes dependent rows.
- `UniqueConstraint(...)` prevents duplicates such as two files with the same path in one project.
- `Index(...)` marks access patterns the app will query often, like reverse citation lookup.
- JSONB `metadata` columns preserve source-specific fields without changing schema for every provider.

## `backend/app/deps.py`

Bridges `app.state` (owned by the lifespan) to route handlers via `Depends`. `get_db` is a generator dependency: session opens before the handler, closes after the response — even on exceptions.

```python
# AsyncIterator is the type of a dependency that yields a value and then cleans up.
from collections.abc import AsyncIterator

# ArqRedis is the queue client used by API routes/tools to enqueue background jobs.
from arq.connections import ArqRedis
# Request gives dependencies access to the current FastAPI app and app.state.
from fastapi import Request
# AsyncDriver is Neo4j's connection-pool object.
from neo4j import AsyncDriver
# Redis is the async Redis client for cache/simple commands.
from redis.asyncio import Redis
# AsyncSession is the per-request SQLAlchemy session type.
from sqlalchemy.ext.asyncio import AsyncSession

# Settings is returned so routes/tools can read typed config if needed.
from app.config import Settings


def get_app_settings(request: Request) -> Settings:
    # Settings was created during lifespan startup and stored on app.state.
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    # session_factory creates a fresh AsyncSession for this request.
    async with request.app.state.session_factory() as session:
        # Yield hands the session to the route handler; `async with` closes it afterward.
        yield session


def get_neo4j(request: Request) -> AsyncDriver:
    # Neo4j driver is process-wide; handlers open sessions from it when needed.
    return request.app.state.neo4j


def get_redis(request: Request) -> Redis:
    # Redis client is process-wide; used for caches and quick pings.
    return request.app.state.redis


def get_arq_pool(request: Request) -> ArqRedis:
    # arq pool is process-wide; routes/tools use it to enqueue worker jobs.
    return request.app.state.arq_pool
```

Walkthrough:

- `deps.py` is the bridge between FastAPI routes and lifespan-created clients.
- Routes ask for dependencies with `Depends(get_db)` instead of importing globals.
- This makes route handlers easier to test and keeps connection ownership centralized.

## `backend/app/main.py`

App factory + lifespan. Everything before `yield` is startup, everything after is shutdown (reverse order). The arq pool lives here because API routes and tools enqueue jobs. Compose healthchecks guarantee the stores are up before this runs.

Requires `app/api/router.py` (guide 08) and `app/graph/` (guide 02) to import cleanly — create those before first boot, or temporarily comment the imports out.

```python
# AsyncIterator is the return type for FastAPI's async lifespan context manager.
from collections.abc import AsyncIterator
# asynccontextmanager lets one function express startup before `yield` and shutdown after.
from contextlib import asynccontextmanager

# Separate Redis client for normal Redis commands/cache.
import redis.asyncio as aioredis
# create_pool builds the arq queue client.
from arq import create_pool
# RedisSettings parses the Redis DSN for arq.
from arq.connections import RedisSettings
# FastAPI is the ASGI app class.
from fastapi import FastAPI
# CORS middleware lets the Vite frontend call the backend from a different origin.
from fastapi.middleware.cors import CORSMiddleware

# One router gathers all API route modules.
from app.api.router import api_router
# Settings are parsed once and stored on app.state.
from app.config import get_settings
# Postgres lifecycle helpers and startup vector-dimension guard.
from app.db.postgres import check_embedding_dimension, create_engine, create_session_factory
# Neo4j driver lifecycle helper.
from app.graph.neo4j_client import create_neo4j_driver
# Neo4j constraints are applied on every startup, idempotently.
from app.graph.schema import apply_constraints
# Structured logging setup.
from app.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Parse settings once at startup.
    settings = get_settings()
    # Configure logging before doing startup work that might log.
    configure_logging()
    # Create a module logger for startup/shutdown events.
    log = get_logger(__name__)

    # Store settings on app.state so dependencies can retrieve them per request.
    app.state.settings = settings
    # Create one Postgres engine/pool per process.
    app.state.db_engine = create_engine(settings)
    # Create a session factory that borrows connections from the engine.
    app.state.session_factory = create_session_factory(app.state.db_engine)
    # Create one Neo4j driver/pool per process.
    app.state.neo4j = create_neo4j_driver(settings)
    # Create one Redis client for cache/ping operations.
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # Create one arq Redis pool for enqueueing background jobs.
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

    # Ensure Neo4j uniqueness constraints/indexes exist before graph sync runs.
    await apply_constraints(app.state.neo4j)
    # Ensure env embedding dimension matches the migrated pgvector column.
    await check_embedding_dimension(app.state.db_engine, settings.EMBEDDING_DIM)
    # Emit one structured startup event.
    log.info("app.startup", env=settings.APP_ENV)

    # FastAPI serves requests while execution is paused at this yield.
    yield

    # Shutdown runs in reverse acquisition order.
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()
    await app.state.neo4j.close()
    await app.state.db_engine.dispose()
    # Emit one structured shutdown event after clients are closed.
    log.info("app.shutdown")


def create_app() -> FastAPI:
    # App factory lets tests create isolated app instances.
    settings = get_settings()
    # Lifespan wires startup/shutdown into the ASGI app.
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    # Browser frontend runs on a different origin from FastAPI, so allow it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Mount all `/api/...` routes.
    app.include_router(api_router)
    return app


# Uvicorn imports this object from `app.main:app`.
app = create_app()
```

Walkthrough:

- The lifespan function is the composition root: all shared clients are created here.
- `app.state` is FastAPI's process-local bag for shared runtime objects.
- `create_app()` is intentionally separate from `app = create_app()` so tests can build fresh apps.
- Shutdown closes clients explicitly so Docker restarts and tests do not leak connections.

---

## Alembic (all files, complete)

### `backend/alembic.ini`

```ini
[alembic]
script_location = alembic
sqlalchemy.url =
```

(URL is injected from `Settings` in `env.py`; keep the ini minimal.)

Walkthrough:

- `script_location = alembic` tells Alembic where migration scripts live.
- `sqlalchemy.url =` stays blank because `env.py` reads the real URL from `Settings`.
- Keeping secrets out of `alembic.ini` prevents accidentally committing DB credentials.

### `backend/alembic/env.py`

Async variant: Alembic's migration functions are sync, so we open an async connection and hop into them with `run_sync`.

```python
# Alembic is sync-oriented; asyncio lets us run its sync hooks through an async engine.
import asyncio

# `context` is Alembic's runtime object for configuring and running migrations.
from alembic import context
# NullPool means migration connections are not reused after the migration command exits.
from sqlalchemy import pool
# Sync connection type used by Alembic's migration callbacks.
from sqlalchemy.engine import Connection
# Helper that creates an AsyncEngine from Alembic config.
from sqlalchemy.ext.asyncio import async_engine_from_config

# Settings supplies DATABASE_URL.
from app.config import get_settings
# Base.metadata tells Alembic what tables/models exist.
from app.db.models import Base

# Alembic provides this config object when it loads env.py.
config = context.config
# Inject the real database URL from environment/settings.
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)
# Metadata is used for future autogenerate comparisons.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Offline mode emits SQL without opening a DB connection.
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    # Alembic wraps migration operations in one transaction where supported.
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Configure Alembic with a real sync connection.
    context.configure(connection=connection, target_metadata=target_metadata)
    # Run upgrade/downgrade functions inside a transaction.
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Build an async engine using the injected sqlalchemy.url.
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Open async connection, then give Alembic a sync facade via run_sync.
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    # Dispose the migration engine when the CLI command ends.
    await connectable.dispose()


if context.is_offline_mode():
    # `alembic upgrade --sql` path.
    run_migrations_offline()
else:
    # Normal `alembic upgrade head` path.
    asyncio.run(run_async_migrations())
```

Walkthrough:

- Alembic migrations are fundamentally synchronous functions.
- Your app uses asyncpg, so `env.py` builds an async engine and bridges into sync migration callbacks.
- `Base.metadata` is not used by the raw SQL first migration, but it is useful for later autogenerate.

### `backend/alembic/script.py.mako`

Template Alembic uses for future `alembic revision` commands.

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Walkthrough:

- `script.py.mako` is a template, not runtime app code.
- `${message}`, `${up_revision}`, and friends are filled by Alembic when it creates new revisions.
- Keeping this standard means future `alembic revision -m "..."` files come out predictable.
- `upgrade()` moves the schema forward; `downgrade()` reverses it when possible.

### `backend/alembic/versions/0001_initial_schema.py`

Raw SQL, verbatim from the blueprint — the migration *is* the schema spec. One `op.execute` per statement (asyncpg can't prepare multi-statement strings). The `vector` extension is created here so it works on fresh and existing volumes.

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""
from alembic import op

# Alembic revision identifiers. `down_revision = None` means this is the first migration.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Each string is one SQL statement. asyncpg/Alembic is happiest when statements are executed separately.
TABLES = [
    """
    CREATE TABLE users (
      id UUID PRIMARY KEY,
      email TEXT UNIQUE,
      display_name TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE projects (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL REFERENCES users(id),
      name TEXT NOT NULL,
      description TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE project_files (
      id UUID PRIMARY KEY,
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      path TEXT NOT NULL,
      content TEXT NOT NULL,
      version INT NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(project_id, path)
    )
    """,
    """
    CREATE TABLE file_versions (
      id UUID PRIMARY KEY,
      file_id UUID NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
      version INT NOT NULL,
      content TEXT NOT NULL,
      created_by TEXT NOT NULL DEFAULT 'user',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(file_id, version)
    )
    """,
    """
    CREATE TABLE papers (
      id UUID PRIMARY KEY,
      openalex_id TEXT UNIQUE,
      semantic_scholar_id TEXT UNIQUE,
      doi TEXT UNIQUE,
      title TEXT,
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
    )
    """,
    """
    CREATE TABLE authors (
      id UUID PRIMARY KEY,
      openalex_id TEXT UNIQUE,
      semantic_scholar_id TEXT UNIQUE,
      name TEXT NOT NULL,
      metadata JSONB NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE paper_authors (
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      author_id UUID NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
      author_order INT,
      PRIMARY KEY (paper_id, author_id)
    )
    """,
    """
    CREATE TABLE citations (
      citing_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      cited_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      source TEXT NOT NULL DEFAULT 'openalex',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (citing_paper_id, cited_paper_id)
    )
    """,
    """
    CREATE TABLE concepts (
      id UUID PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      type TEXT NOT NULL DEFAULT 'concept',
      metadata JSONB NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE paper_concepts (
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
      score FLOAT,
      source TEXT NOT NULL DEFAULT 'openalex',
      PRIMARY KEY (paper_id, concept_id)
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE project_papers (
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      bibtex_key TEXT NOT NULL,
      added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, paper_id),
      UNIQUE(project_id, bibtex_key)
    )
    """,
    """
    CREATE TABLE agent_sessions (
      id UUID PRIMARY KEY,
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      user_id UUID NOT NULL REFERENCES users(id),
      title TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE agent_messages (
      id UUID PRIMARY KEY,
      session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      metadata JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE jobs (
      id UUID PRIMARY KEY,
      job_type TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      queue_job_id TEXT,
      input JSONB NOT NULL DEFAULT '{}',
      result JSONB,
      error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
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
    )
    """,
]

# Indexes live outside CREATE TABLE because they optimize query access patterns.
INDEXES = [
    "CREATE INDEX citations_cited_idx ON citations (cited_paper_id)",
    "CREATE INDEX agent_messages_session_idx ON agent_messages (session_id, created_at)",
    """
    CREATE INDEX paper_chunks_embedding_hnsw_idx
    ON paper_chunks USING hnsw (embedding vector_cosine_ops)
    """,
]

# Drop order is reverse dependency order: children first, parents last.
TABLE_NAMES = [
    "latex_compilations", "jobs", "tool_calls", "agent_messages", "agent_sessions",
    "project_papers", "paper_chunks", "paper_concepts", "concepts", "citations",
    "paper_authors", "authors", "papers", "file_versions", "project_files",
    "projects", "users",
]


def upgrade() -> None:
    # pgvector extension must exist before creating `embedding vector(1536)`.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Create all tables in parent-before-child order.
    for statement in TABLES:
        op.execute(statement)
    # Create indexes after tables exist.
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    # Drop tables in dependency-safe order. CASCADE cleans up constraints/indexes.
    for table in TABLE_NAMES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
```

Migration walkthrough:

- `CREATE EXTENSION IF NOT EXISTS vector`: enables pgvector inside this database.
- `users`: MVP identity table; one dev user is seeded later.
- `projects`: top-level workspace records.
- `project_files`: current file contents and version number.
- `file_versions`: historical snapshots for explicit saves and agent patches.
- `papers`: canonical scholarly entities; stubs are allowed by nullable `title`.
- `authors`/`paper_authors`: normalized many-to-many authorship.
- `citations`: durable directed citation edges; Neo4j mirrors them.
- `concepts`/`paper_concepts`: structured topics used by graph retrieval.
- `paper_chunks`: text chunks plus embeddings for vector search.
- `project_papers`: project-specific imported papers and BibTeX keys.
- `agent_sessions`/`agent_messages`: chat history and context.
- `tool_calls`: observable audit trail for the agent and MCP tools.
- `jobs`: durable status rows for worker jobs; the UI polls this table via API.
- `latex_compilations`: compile attempts, logs, errors, and PDF artifact paths.
- `citations_cited_idx`: speeds up “who cites this paper?” reverse lookups.
- `agent_messages_session_idx`: speeds chronological chat history loads.
- `paper_chunks_embedding_hnsw_idx`: approximate nearest-neighbor vector index for pgvector.

---

## Acceptance checks

```bash
make up                                             # or docker compose up --build
docker compose exec backend alembic upgrade head
docker compose exec backend pytest app/tests/test_health.py
curl http://localhost:8000/api/health
```

Expected:

- migration creates all 17 tables + hnsw index (`\dt` and `\di` in `psql -U citepilot citepilot`),
- `/api/health` returns per-store status; `docker compose stop postgres` flips it to `degraded`, `start` heals it,
- startup logs `app.startup` as one JSON line; `SHOW CONSTRAINTS` in the Neo4j browser lists four constraints,
- startup does **not** crash on the embedding-dim check (it matches 1536).

## Why-it's-built-this-way (interview points)

- **Postgres is the source of truth; Neo4j is derived.** If Neo4j dies, `make resync-graph` rebuilds it. Two stores, one owner.
- **Lifespan pattern**: engines/drivers are pools; one per process, per-request sessions via DI. This is the standard async-FastAPI production answer.
- **Raw-SQL first migration**: the blueprint's SQL is the contract; hand-rolled ORM autogenerate drift can't sneak in. Real projects use `alembic revision --autogenerate` after this baseline.
- **`is_stub` on papers** is what makes the citation graph dense from the first import (guide 03).
