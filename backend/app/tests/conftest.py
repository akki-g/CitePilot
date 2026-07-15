from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Project, User
from app.db.postgres import create_engine, create_session_factory
from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with LifespanManager(app):   # runs lifespan; plain ASGI transport would skip it
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session: AsyncSession) -> Project:
    """A project owned by the (idempotently created) dev user."""
    settings = get_settings()
    user = await db_session.get(User, UUID(settings.DEV_USER_ID))
    if user is None:
        user = User(
            id=UUID(settings.DEV_USER_ID), email="dev@citepilot.local", display_name="Dev User"
        )
        db_session.add(user)
        await db_session.flush()
    proj = Project(user_id=user.id, name="test-project")
    db_session.add(proj)
    await db_session.commit()
    return proj
