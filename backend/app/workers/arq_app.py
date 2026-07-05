from arq.connections import RedisSettings

from app.config import get_settings
from app.logging import configure_logging
from app.workers import jobs


async def startup(ctx: dict) -> None:
    configure_logging()
    ctx["deps"] = jobs.WorkerDeps()


async def shutdown(ctx: dict) -> None:
    await ctx["deps"].aclose()


class WorkerSettings:
    functions = [
        jobs.ingest_paper_job,
        jobs.expand_citation_graph_job,
        jobs.embed_chunks_job,
        jobs.compile_latex_job,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_jobs = 4
    job_timeout = 300
