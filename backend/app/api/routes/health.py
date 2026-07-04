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

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, **checks}
