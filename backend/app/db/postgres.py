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
def create_engine(settings: Settings) -> AsyncEngine:
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
        # fix: table name was misspelled 'paper_chuncks' (3 places), so this check silently skipped forever
        exists = (await conn.execute(text("SELECT to_regclass('paper_chunks')"))).scalar()

        if exists is None:
            # on a brand new DB before migrations, warn instead of crashing app
            log.warning("db.embedding_dim_check_skipped", reason="paper_chunks missing, run migrations")
            return

        # pgvector stored vec dim in pg_attribute.atttypmod
        # fix: the two string parts concatenated without a space ('pg_attributeWHERE'), invalid SQL
        typmod = (
            await conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'paper_chunks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
    # fix: pgvector stores the dimension directly in atttypmod (vector(1536) -> typmod 1536);
    # the guide's `typmod - 4` VARHDRSZ offset applies to varchar, not pgvector, and made
    # this check fail at startup with a false "vector(1532)" mismatch
    actual_dim = typmod
    if actual_dim != expected_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={expected_dim} does not match paper_chunks.embedding vector({actual_dim}). "
            "Change the env var or write a migration, do not mix dims"
        )
    

# AsyncEngine is expensive and owns the connection pool, so it belongs in the fastapi lifespan
# AsyncSession is cheap and short lived so each request/job gets its own
