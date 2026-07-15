from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    APP_NAME: str = "CitePilot"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "postgresql+asyncpg://citepilot:citepilot@postgres:5432/citepilot"
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "citepilot-password"
    REDIS_URL: str = "redis://redis:6379/0"

    OPENALEX_MAILTO: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    CROSSREF_MAILTO: str = ""

    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""

    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_DIM: int = 1536

    LATEX_WORKDIR: str = "/tmp/citepilot-latex"
    LATEX_COMPILE_TIMEOUT_SECONDS: int = 30

    # Authentication. Production deployments must replace AUTH_SECRET and enable
    # secure cookies; see README.md for the deployment checklist.
    AUTH_SECRET: str = "development-only-change-me"
    SESSION_COOKIE_NAME: str = "citepilot_session"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_DOMAIN: str | None = None
    SESSION_TTL_DAYS: int = 30
    EMAIL_VERIFICATION_TTL_HOURS: int = 24

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_DISCOVERY_URL: str = (
        "https://accounts.google.com/.well-known/openid-configuration"
    )

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_STARTTLS: bool = True
    SMTP_USE_SSL: bool = False

    # Resend is the recommended production transactional-email path. SMTP
    # remains supported for providers that expose authenticated mail relays.
    RESEND_API_KEY: str = ""

    # Anonymous showcase sandbox. Redis stores only quota counters; demo project
    # files, conversations, and compiled PDFs are never persisted.
    DEMO_ENABLED: bool = True
    DEMO_AGENT_RUN_LIMIT: int = 3
    DEMO_PREVIEW_LIMIT: int = 3
    DEMO_QUOTA_WINDOW_HOURS: int = 24
    DEMO_MAX_SOURCE_BYTES: int = 500_000

    DEV_USER_ID: str = "00000000-0000-0000-0000-000000000001"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_production_settings(settings: Settings) -> None:
    if settings.APP_ENV.casefold() != "production":
        return

    errors: list[str] = []
    insecure_secrets = {
        "development-only-change-me",
        "replace-with-at-least-32-random-bytes",
    }
    if settings.AUTH_SECRET in insecure_secrets or len(settings.AUTH_SECRET) < 32:
        errors.append("AUTH_SECRET must be a unique value of at least 32 characters")
    if not settings.SESSION_COOKIE_SECURE:
        errors.append("SESSION_COOKIE_SECURE must be true")
    if not settings.FRONTEND_URL.startswith("https://"):
        errors.append("FRONTEND_URL must use HTTPS")
    if not settings.BACKEND_URL.startswith("https://"):
        errors.append("BACKEND_URL must use HTTPS")
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        errors.append("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
    if not settings.SMTP_FROM_EMAIL:
        errors.append("SMTP_FROM_EMAIL is required")
    if not settings.RESEND_API_KEY and not settings.SMTP_HOST:
        errors.append("RESEND_API_KEY or SMTP_HOST is required for verification email")
    if settings.SMTP_STARTTLS and settings.SMTP_USE_SSL:
        errors.append("SMTP_STARTTLS and SMTP_USE_SSL cannot both be true")
    if errors:
        raise RuntimeError("Unsafe production auth configuration: " + "; ".join(errors))
