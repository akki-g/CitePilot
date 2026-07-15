import pytest

from app.auth.security import hash_secret, normalize_email, password_hash, verify_secret
from app.config import Settings, validate_production_settings


def test_password_hash_is_not_reversible_and_verifies():
    encoded = password_hash.hash("a-long-demo-password")

    assert "a-long-demo-password" not in encoded
    assert password_hash.verify("a-long-demo-password", encoded)
    assert not password_hash.verify("wrong-password", encoded)


def test_opaque_secrets_compare_by_hash():
    digest = hash_secret("browser-secret")

    assert verify_secret("browser-secret", digest)
    assert not verify_secret("different-secret", digest)


def test_email_normalization_is_stable():
    assert normalize_email("  Person@Example.COM ") == "person@example.com"


def test_unsafe_production_auth_configuration_fails_closed():
    settings = Settings(APP_ENV="production")

    with pytest.raises(RuntimeError, match="Unsafe production auth configuration"):
        validate_production_settings(settings)


def test_secure_production_auth_configuration_is_accepted():
    settings = Settings(
        APP_ENV="production",
        AUTH_SECRET="x" * 48,
        SESSION_COOKIE_SECURE=True,
        FRONTEND_URL="https://citepilot.example.com",
        BACKEND_URL="https://api.citepilot.example.com",
        GOOGLE_CLIENT_ID="client-id",
        GOOGLE_CLIENT_SECRET="client-secret",
        SMTP_HOST="smtp.example.com",
        SMTP_FROM_EMAIL="hello@example.com",
    )

    validate_production_settings(settings)
