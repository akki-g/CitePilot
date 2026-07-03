import os 

from arq.connections import RedisSettings

async def ping(ctx: dict) -> str:
    "Placeholder job proving the worker boots and consumes the queue"
    return "pong"

class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://redis:6379/0"))

