import hashlib
import random

from typing import Protocol
import httpx
from app.config import Settings

class EmbeddingClient(Protocol):
    async def embed_text(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbeddingClient:
    """Deterministic pseudo-random vectors keyed on the text's hash."""

    def __init__(self, dim: int = 1536):
        # Match settings.EMBEDDING_DIM so tests mirror production vector shape.
        self.dim = dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            # Hash text into a stable seed so the same text always gets the same vector.
            seed = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            # Values do not need semantic meaning for unit tests; determinism is enough.
            vectors.append([rng.uniform(-1.0, 1.0) for _ in range(self.dim)])
        return vectors


class OpenAIEmbeddingClient:
    def __init__(self, settings: Settings):
        # Fail at construction if the real provider is selected but not configured.
        if not settings.EMBEDDING_API_KEY:
            raise ValueError("EMBEDDING_API_KEY is required for OpenAI embeddings")
        if not settings.EMBEDDING_MODEL:
            raise ValueError("EMBEDDING_MODEL is required for OpenAI embeddings")
        self.model = settings.EMBEDDING_MODEL
        self.api_key = settings.EMBEDDING_API_KEY
        self.client = httpx.AsyncClient(timeout=60)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # OpenAI embeddings endpoint accepts a batch of strings.
        resp = await self.client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # API may return items with explicit indexes; sort to preserve input order.
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


def create_embedding_client(settings: Settings) -> EmbeddingClient:
    # Test env always uses the fake so tests never call external APIs.
    if settings.APP_ENV == "test":
        return FakeEmbeddingClient(dim=settings.EMBEDDING_DIM)
    if settings.EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddingClient(settings)
    raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")