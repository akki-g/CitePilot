import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from pwdlib import PasswordHash

from app.config import Settings


password_hash = PasswordHash.recommended()
# A precomputed-shape hash keeps unknown-email login attempts on the same slow path.
DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-user-password")


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def verify_secret(value: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(value), expected_hash)


def session_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.SESSION_TTL_DAYS)


def verification_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(hours=settings.EMAIL_VERIFICATION_TTL_HOURS)


def set_session_cookies(
    response: Response,
    settings: Settings,
    *,
    session_token: str,
    csrf_token: str,
) -> None:
    max_age = settings.SESSION_TTL_DAYS * 24 * 60 * 60
    cookie_options = {
        "secure": settings.SESSION_COOKIE_SECURE,
        "samesite": "lax",
        "path": "/",
        "domain": settings.SESSION_COOKIE_DOMAIN or None,
        "max_age": max_age,
    }
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        "citepilot_csrf",
        csrf_token,
        httponly=False,
        **cookie_options,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (settings.SESSION_COOKIE_NAME, "citepilot_csrf"):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.SESSION_COOKIE_DOMAIN or None,
            secure=settings.SESSION_COOKIE_SECURE,
            samesite="lax",
        )
