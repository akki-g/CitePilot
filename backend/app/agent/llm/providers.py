from app.agent.llm.anthropic_client import AnthropicClient
from app.agent.llm.base import LLMClient
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.openai_client import OpenAIClient
from app.config import Settings


def create_llm_client(settings: Settings) -> LLMClient:
    # Tests should never call external LLM providers.
    if settings.APP_ENV == "test":
        return FakeLLMClient([])
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient(settings.LLM_API_KEY, settings.LLM_MODEL)
    if settings.LLM_PROVIDER == "openai":
        return OpenAIClient(settings.LLM_API_KEY, settings.LLM_MODEL)
    raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")