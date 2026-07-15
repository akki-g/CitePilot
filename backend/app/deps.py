# bridges app.state (owned by the lifespan) to route handlers via depends
# get_db is a generator dependency: session opens before the handler, closes after the response, even on exceptions

# AsyncIterator type of dependency that yields a value and then cleans up
from collections.abc import AsyncIterator

# ArqRedis is the queue client used by the API routes/tools to enqueue background jobs
from arq.connections import ArqRedis

from fastapi import Request
from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm.base import LLMClient
from app.agent.llm.providers import create_llm_client
from app.config import Settings

def get_app_settings(request: Request) -> Settings:
    # settings was created during lifespan startup and stored on app.state
    return request.app.state.settings

# fix: get_db returned the Neo4j driver instead of a DB session; rewrote it as a generator
# dependency that yields an AsyncSession from app.state.session_factory
async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    # session_factory creates a fresh AsyncSession for this request
    async with request.app.state.session_factory() as session:
        # yield hands the session to the route handler; `async with` closes it afterward
        yield session

# fix: get_neo4j was missing entirely; routes import it, so the app failed at import time
def get_neo4j(request: Request) -> AsyncDriver:
    # Neo4j driver is process wide; handlers open sessions from it when needed
    return request.app.state.neo4j

def get_redis(request: Request) -> Redis:
    # redis client is process wide; used for caches and quick pings
    return request.app.state.redis

def get_arq_pool(request: Request) -> ArqRedis:
    # arq pool is process wide; routes/tools use it to enqueue worker jobs
    return request.app.state.arq_pool


async def get_llm(request: Request) -> LLMClient:
    """Return one process-wide provider client with a warm connection pool."""
    if request.app.state.llm is None:
        async with request.app.state.llm_lock:
            if request.app.state.llm is None:
                request.app.state.llm = create_llm_client(request.app.state.settings)
    return request.app.state.llm
