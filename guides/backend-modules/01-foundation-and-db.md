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

---

## `backend/app/config.py`

Field names match `.env.example` exactly; pydantic-settings maps env vars case-insensitively. `@lru_cache` = parse env once per process. Typos in env values fail at boot, not at 2am.

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    APP_NAME: str = "CitePilot"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "postgresql+asyncpg://citepilot:citepilot@postgres:5432/citepilot"
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "citepilot-password"
    REDIS_URL: str = "redis://redis:6379/0"

    OPENALEX_MAILTO: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    CROSSREF_MAILTO: str = ""

    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""

    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_DIM: int = 1536

    LATEX_WORKDIR: str = "/tmp/citepilot-latex"
    LATEX_COMPILE_TIMEOUT_SECONDS: int = 30

    DEV_USER_ID: str = "00000000-0000-0000-0000-000000000001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

## `backend/app/logging.py`

JSON logs on stdout — what Docker and log aggregators expect. Convention for the whole project: event names are stable dotted strings (`paper.import.started`), data goes in fields, never f-strings.

```python
import logging
import sys

import structlog


def configure_logging() -> None:
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

Note: naming this module `app/logging.py` is safe — Python 3 imports are absolute, so `import logging` inside the package still gets the stdlib.

## `backend/app/db/postgres.py`

- `pool_pre_ping` — pool self-heals after a Postgres restart.
- `expire_on_commit=False` — mandatory with async sessions; otherwise touching an ORM object after commit triggers a lazy refresh, which blows up under asyncio ("greenlet" errors).
- `check_embedding_dimension` — the pgvector column dim is frozen at migration time; if `EMBEDDING_DIM` in env disagrees, fail loudly at startup instead of storing garbage vectors. Skips quietly if migrations haven't run yet.

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.logging import get_logger

log = get_logger(__name__)


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_embedding_dimension(engine: AsyncEngine, expected_dim: int) -> None:
    async with engine.connect() as conn:
        exists = (await conn.execute(text("SELECT to_regclass('paper_chunks')"))).scalar()
        if exists is None:
            log.warning("db.embedding_dim_check_skipped", reason="paper_chunks missing; run migrations")
            return
        typmod = (
            await conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'paper_chunks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
    actual_dim = typmod - 4  # pgvector stores dim in typmod with a 4-byte header offset
    if actual_dim != expected_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={expected_dim} does not match paper_chunks.embedding vector({actual_dim}). "
            "Change the env var or write a migration; do not mix dimensions."
        )
```

## `backend/app/db/models.py`

Matches the blueprint SQL exactly. Three things to notice while typing:

- `metadata` is a reserved attribute on SQLAlchemy declarative classes, so the Python attribute is `paper_metadata`/etc. mapped to a column literally named `"metadata"`.
- `title` on `papers` is nullable — **stub papers** (references we haven't imported yet) have no title.
- The helper functions return a fresh `mapped_column(...)` per call; annotating them as `Mapped[...]` keeps the class bodies terse.

```python
import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

## `backend/app/deps.py`

Bridges `app.state` (owned by the lifespan) to route handlers via `Depends`. `get_db` is a generator dependency: session opens before the handler, closes after the response — even on exceptions.

```python
from collections.abc import AsyncIterator

from arq.connections import ArqRedis
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


def get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool
```

## `backend/app/main.py`

App factory + lifespan. Everything before `yield` is startup, everything after is shutdown (reverse order). The arq pool lives here because API routes and tools enqueue jobs. Compose healthchecks guarantee the stores are up before this runs.

Requires `app/api/router.py` (guide 08) and `app/graph/` (guide 02) to import cleanly — create those before first boot, or temporarily comment the imports out.

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.db.postgres import check_embedding_dimension, create_engine, create_session_factory
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
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))

    await apply_constraints(app.state.neo4j)
    await check_embedding_dimension(app.state.db_engine, settings.EMBEDDING_DIM)
    log.info("app.startup", env=settings.APP_ENV)

    yield

    await app.state.arq_pool.aclose()
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

---

## Alembic (all files, complete)

### `backend/alembic.ini`

```ini
[alembic]
script_location = alembic
sqlalchemy.url =
```

(URL is injected from `Settings` in `env.py`; keep the ini minimal.)

### `backend/alembic/env.py`

Async variant: Alembic's migration functions are sync, so we open an async connection and hop into them with `run_sync`.

```python
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

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

### `backend/alembic/versions/0001_initial_schema.py`

Raw SQL, verbatim from the blueprint — the migration *is* the schema spec. One `op.execute` per statement (asyncpg can't prepare multi-statement strings). The `vector` extension is created here so it works on fresh and existing volumes.

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

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

INDEXES = [
    "CREATE INDEX citations_cited_idx ON citations (cited_paper_id)",
    "CREATE INDEX agent_messages_session_idx ON agent_messages (session_id, created_at)",
    """
    CREATE INDEX paper_chunks_embedding_hnsw_idx
    ON paper_chunks USING hnsw (embedding vector_cosine_ops)
    """,
]

TABLE_NAMES = [
    "latex_compilations", "jobs", "tool_calls", "agent_messages", "agent_sessions",
    "project_papers", "paper_chunks", "paper_concepts", "concepts", "citations",
    "paper_authors", "authors", "papers", "file_versions", "project_files",
    "projects", "users",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for statement in TABLES:
        op.execute(statement)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    for table in TABLE_NAMES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
```

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
