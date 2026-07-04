from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from app.api.router import api_router 
from app.config import get_settings
from app.db.postgres import check_embedding_dimension, create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver
from app.graph.schema import apply_constraints
from app.logging import configure_logging, get_logger


