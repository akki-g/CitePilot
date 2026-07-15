# fix: file was truncated at the imports — lifespan, create_app, CORS, and the
# module-level `app` object were missing, so `uvicorn app.main:app` could not boot
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.auth.middleware import CSRFMiddleware
from app.config import get_settings, validate_production_settings
from app.db.postgres import check_embedding_dimension, create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver
from app.graph.schema import apply_constraints
from app.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # parse settings once at startup; configure logging before startup work that might log
    settings = get_settings()
    validate_production_settings(settings)
    configure_logging()
    log = get_logger(__name__)

    # app.state is FastAPI's process-local bag for shared runtime objects
    app.state.settings = settings
    # one Postgres engine/pool per process; sessions borrow connections from it
    app.state.db_engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.db_engine)
    # one Neo4j driver/pool per process
    app.state.neo4j = create_neo4j_driver(settings)
    # one Redis client for cache/ping operations
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # one arq Redis pool for enqueueing background jobs
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    # The provider client is created lazily on the first agent turn, then reused
    # so later turns keep their HTTP/TLS connection warm.
    app.state.llm = None
    app.state.llm_lock = asyncio.Lock()
    app.state.demo_compile_semaphore = asyncio.Semaphore(2)

    # ensure Neo4j uniqueness constraints/indexes exist before graph sync runs
    await apply_constraints(app.state.neo4j)
    # ensure env embedding dimension matches the migrated pgvector column
    await check_embedding_dimension(app.state.db_engine, settings.EMBEDDING_DIM)
    log.info("app.startup", env=settings.APP_ENV)

    # FastAPI serves requests while execution is paused at this yield
    yield

    # shutdown runs in reverse acquisition order
    llm_close = getattr(app.state.llm, "aclose", None)
    if llm_close:
        await llm_close()
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()
    await app.state.neo4j.close()
    await app.state.db_engine.dispose()
    log.info("app.shutdown")


def create_app() -> FastAPI:
    # app factory lets tests create isolated app instances
    settings = get_settings()
    validate_production_settings(settings)
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    app.state.settings = settings

    oauth = OAuth()
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        oauth.register(
            name="google",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            server_metadata_url=settings.GOOGLE_DISCOVERY_URL,
            client_kwargs={"scope": "openid email profile"},
        )
    app.state.oauth = oauth

    # Authlib uses this short-lived signed cookie only for OAuth state/nonce. Login
    # sessions are separate opaque tokens backed by Postgres.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.AUTH_SECRET,
        session_cookie="citepilot_oauth",
        max_age=600,
        same_site="lax",
        https_only=settings.SESSION_COOKIE_SECURE,
    )
    app.add_middleware(CSRFMiddleware)
    # browser frontend runs on a different origin from FastAPI, so allow it
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # The demo compiler reports its server-side allowance in this header.
        # Without explicitly exposing it, browsers hide the value from fetch()
        # and the UI incorrectly falls back to zero after the first preview.
        expose_headers=["X-Demo-Remaining"],
    )
    # mount all `/api/...` routes
    app.include_router(api_router)
    return app


# uvicorn imports this object from `app.main:app`
app = create_app()
