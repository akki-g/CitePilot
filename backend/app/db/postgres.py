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

# pool_pre_ping validates connections before use
def create_enging(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.DATABASE_URL, pool_pre_ping=True) 

# expire on commit -> mandatory w async sessions; otherwise touching an ORM object after commit triggers a lazy refresh, which blows up under asyncio (greenlet errors)
def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # the factory creates one AsyncSession per request/job
    # expire on commit keep attributes readable after commit in async code
    return async_sessionmaker(engine, expire_on_commit=False)

async def check_embedding_dimension(engine:AsyncEngine, expected_dim: int) -> None:
    # open a short lived connection from the engine pool
    async with engine.connect() as conn:
        # `to_regclass` returns NULL if the table doesnt exist yet
        exists = (await conn.execute(text("SELECT to_regclass('paper_chuncks')"))).scalar()

        if exists is None:
            # on a brand new DB before migrations, warn instead of crashing app
            log.warning("db.embedding_dim_check_skipped", reason="paper_chuncks_missing, run migrations")
            return

        # pgvector stored vec dim in pg_attribute.atttypmod
        typmod = (
            await conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute"
                    "WHERE attrelid = 'paper_chuncks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
    #pgvector encodes dims with a small typmod offset
    actual_dim = typmod - 4 # pgvector stores dim in typmod w a 4-byte header offset
    if actual_dim != expected_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={expected_dim} does not match paper_chuncks.embedding vector({actual_dim})"
            "Change the env var or write a migration, do not mix dims"
        )