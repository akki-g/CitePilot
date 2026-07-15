# fix: this file (and alembic.ini, script.py.mako, versions/0001_initial_schema.py) was
# missing entirely — created from guide 01 so `alembic upgrade head` can build the schema
# Alembic is sync-oriented; asyncio lets us run its sync hooks through an async engine.
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.models import Base

# Alembic provides this config object when it loads env.py.
config = context.config
# Inject the real database URL from environment/settings.
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)
# Metadata is used for future autogenerate comparisons.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Offline mode emits SQL without opening a DB connection.
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Configure Alembic with a real sync connection.
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Build an async engine using the injected sqlalchemy.url.
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Open async connection, then give Alembic a sync facade via run_sync.
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
