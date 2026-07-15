import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_secret, verify_secret
from app.db.models import Project, User, UserSession
from app.deps import get_db


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    settings = request.app.state.settings
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None

    row = await db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_secret(token),
            UserSession.expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
    )
    result = row.first()
    if result is None:
        return None
    session, user = result
    csrf_token = request.cookies.get("citepilot_csrf", "")
    if not csrf_token or not verify_secret(csrf_token, session.csrf_token_hash):
        return None
    return user


async def require_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


async def require_verified_user(user: Annotated[User, Depends(require_user)]) -> User:
    if user.email_verified_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email verification required")
    return user


async def get_owned_project(
    db: AsyncSession,
    user: User,
    project_id: uuid.UUID,
) -> Project:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    if project is None:
        # Do not reveal whether another account owns the identifier.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project
