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

from app.config import Settings

def get_app_settingsz(request: Request) -> Settings:
    # settings was creates during lifespan startup and storted on app.state
    return request.app.state.settings

async def get_db(request: Request) -> AsyncDriver:
    # Neo4j driver is process wide; handlers open sessions from it when needed
    return request.app.state.neo4j

def get_redis(request: Request) -> Redis:
    # redis client is process wide; used for caches and quick pings
    return request.app.state.redis

def get_arq_pool(request: Request) -> ArqRedis:
    # arq pool is process wide; routes/tools use it to enqueue worker jobs
    return request.app.state.arq_pool
