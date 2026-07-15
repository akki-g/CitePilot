import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from authlib.integrations.base_client.errors import OAuthError
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_optional_user
from app.auth.email import (
    EmailDeliveryError,
    EmailDeliveryNotConfigured,
    send_verification_email,
    verification_url,
)
from app.auth.security import (
    DUMMY_PASSWORD_HASH,
    clear_session_cookies,
    hash_secret,
    new_secret,
    normalize_email,
    password_hash,
    session_expiry,
    set_session_cookies,
    verification_expiry,
)
from app.config import Settings
from app.db.models import AccountToken, OAuthIdentity, User, UserSession
from app.deps import get_app_settings, get_db


router = APIRouter()


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        try:
            return normalize_email(validate_email(value, check_deliverability=False).normalized)
        except EmailNotValidError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    email_verified: bool


class MessageResponse(BaseModel):
    message: str


class SignupResponse(MessageResponse):
    delivery: str = "email"
    verification_url: str | None = None


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email or "",
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email_verified=user.email_verified_at is not None,
    )


async def _rate_limit(request: Request, key: str, *, limit: int, seconds: int) -> None:
    redis = request.app.state.redis
    full_key = f"auth-rate:{key}"
    attempts = await redis.incr(full_key)
    if attempts == 1:
        await redis.expire(full_key, seconds)
    if attempts > limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _email_rate_key(email: str) -> str:
    # Avoid putting account identifiers into Redis key names.
    return hash_secret(normalize_email(email))[:24]


async def _deliver_verification(
    settings: Settings,
    email: str,
    token: str,
) -> SignupResponse:
    try:
        await send_verification_email(settings, email, token)
    except EmailDeliveryNotConfigured:
        if settings.APP_ENV.casefold() != "production":
            return SignupResponse(
                message="Email delivery is not configured. Use the local verification link below.",
                delivery="development",
                verification_url=verification_url(settings, token),
            )
        raise HTTPException(status_code=503, detail="Verification email is not configured")
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=502,
            detail="We could not send the verification email. Please try again.",
        ) from exc
    return SignupResponse(message="Check your email for a verification link.")


async def _new_verification_token(
    db: AsyncSession,
    settings: Settings,
    user: User,
) -> str:
    await db.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == "email_verification",
            AccountToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
    token = new_secret()
    db.add(
        AccountToken(
            user_id=user.id,
            purpose="email_verification",
            token_hash=hash_secret(token),
            expires_at=verification_expiry(settings),
        )
    )
    return token


async def _start_session(
    db: AsyncSession,
    request: Request,
    response: Response,
    settings: Settings,
    user: User,
) -> None:
    await db.execute(delete(UserSession).where(UserSession.expires_at <= datetime.now(UTC)))
    session_token = new_secret()
    csrf_token = new_secret()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_secret(session_token),
            csrf_token_hash=hash_secret(csrf_token),
            expires_at=session_expiry(settings),
            user_agent=request.headers.get("user-agent", "")[:1000] or None,
            ip_address=request.client.host if request.client else None,
        )
    )
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    set_session_cookies(
        response,
        settings,
        session_token=session_token,
        csrf_token=csrf_token,
    )


@router.get("/providers")
async def providers(settings: Annotated[Settings, Depends(get_app_settings)]) -> dict:
    return {"google": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)}


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User | None, Depends(get_optional_user)]) -> UserResponse:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _user_response(user)


@router.post("/signup", response_model=SignupResponse, status_code=202)
async def signup(
    payload: SignupRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SignupResponse:
    await _rate_limit(request, f"signup:{_client_key(request)}", limit=5, seconds=3600)
    candidate_password_hash = password_hash.hash(payload.password)
    existing = await db.scalar(select(User).where(User.email == payload.email))
    token: str | None = None
    if existing is None:
        user = User(
            email=payload.email,
            display_name=payload.display_name,
            password_hash=candidate_password_hash,
        )
        db.add(user)
        await db.flush()
        token = await _new_verification_token(db, settings, user)
        await db.commit()
    elif existing.email_verified_at is None and existing.is_active:
        # A repeated signup is a common recovery path after a provider outage or
        # mistyped browser close. Issue one fresh token without revealing whether
        # the account already existed.
        token = await _new_verification_token(db, settings, existing)
        await db.commit()

    if token is not None:
        return await _deliver_verification(settings, payload.email, token)
    # The response deliberately does not disclose whether a verified account exists.
    return SignupResponse(message="Check your email for a verification link.")


@router.post("/verify-email", response_model=UserResponse)
async def verify_email(
    payload: TokenRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> UserResponse:
    account_token = await db.scalar(
        select(AccountToken).where(
            AccountToken.token_hash == hash_secret(payload.token),
            AccountToken.purpose == "email_verification",
            AccountToken.used_at.is_(None),
            AccountToken.expires_at > datetime.now(UTC),
        )
    )
    if account_token is None:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")

    user = await db.get(User, account_token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
    now = datetime.now(UTC)
    account_token.used_at = now
    user.email_verified_at = now
    await _start_session(db, request, response, settings, user)
    return _user_response(user)


@router.post("/resend-verification", response_model=SignupResponse, status_code=202)
async def resend_verification(
    payload: EmailRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SignupResponse:
    email = normalize_email(payload.email)
    await _rate_limit(
        request,
        f"verify:{_client_key(request)}:{_email_rate_key(email)}",
        limit=3,
        seconds=3600,
    )
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None and user.email_verified_at is None and user.is_active:
        token = await _new_verification_token(db, settings, user)
        await db.commit()
        return await _deliver_verification(settings, email, token)
    return SignupResponse(message="If that account needs verification, a new link is on its way.")


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> UserResponse:
    email = normalize_email(payload.email)
    await _rate_limit(
        request,
        f"login:{_client_key(request)}:{_email_rate_key(email)}",
        limit=10,
        seconds=900,
    )
    user = await db.scalar(select(User).where(User.email == email))
    encoded_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    try:
        valid_password = password_hash.verify(payload.password, encoded_hash)
    except Exception:
        valid_password = False
    if user is None or not valid_password or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Verify your email before signing in")
    await _start_session(db, request, response, settings, user)
    return _user_response(user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        session = await db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_secret(token))
        )
        if session:
            await db.delete(session)
            await db.commit()
    clear_session_cookies(response, settings)


@router.get("/oauth/google")
async def google_login(request: Request):
    settings = request.app.state.settings
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    redirect_uri = f"{settings.BACKEND_URL.rstrip('/')}/api/auth/oauth/google/callback"
    return await request.app.state.oauth.google.authorize_redirect(
        request,
        redirect_uri,
        nonce=secrets.token_urlsafe(24),
    )


@router.get("/oauth/google/callback")
async def google_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = request.app.state.settings
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}?auth_error=oauth_disabled")
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}?auth_error=oauth_failed")

    userinfo = token.get("userinfo") or {}
    subject = userinfo.get("sub")
    email = normalize_email(userinfo.get("email", ""))
    if not subject or not email or not userinfo.get("email_verified"):
        return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}?auth_error=email_unverified")

    identity = await db.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == "google",
            OAuthIdentity.subject == subject,
        )
    )
    user = await db.get(User, identity.user_id) if identity else None
    if user is None:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name=userinfo.get("name"),
                avatar_url=userinfo.get("picture"),
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            await db.flush()
        else:
            user.email_verified_at = user.email_verified_at or datetime.now(UTC)
            user.avatar_url = user.avatar_url or userinfo.get("picture")
        db.add(
            OAuthIdentity(
                user_id=user.id,
                provider="google",
                subject=subject,
                email=email,
            )
        )

    if not user.is_active:
        return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}?auth_error=account_disabled")

    response = RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}?auth=success")
    await _start_session(db, request, response, settings, user)
    return response
