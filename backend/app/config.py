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

    DEV_USER_ID: str = "00000000-0000-0000-0000-000000000001"


@lru_cache
def get_settings() -> Settings:
    return Settings()