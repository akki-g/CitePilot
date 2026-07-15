import asyncio
import hashlib
import json
import random

from typing import Protocol
import httpx
from app.config import Settings
from app.logging import get_logger

log = get_logger(__name__)

# 429/5xx retry policy: the OpenAI embeddings tier throttles easily, and one
# agent turn can embed the same paragraph several times across the tool loop
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.5
RETRYABLE_STATUS = {429, 500, 502, 503, 529}

# cached query vectors: same text + model always embeds the same, so repeat
# embeds within a session are pure waste against the rate limit
CACHE_TTL_SECONDS = 24 * 3600


class EmbeddingRateLimitError(Exception):
    """Raised when the provider still throttles after retries; callers surface
    this as a tool error instead of letting a raw httpx error kill the turn."""


class EmbeddingClient(Protocol):
    # fix: protocol method was `embed_text` but every implementation/caller uses `embed_texts`
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


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
        last_status = 0
        for attempt in range(MAX_ATTEMPTS):
            resp = await self.client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            if resp.status_code not in RETRYABLE_STATUS:
                resp.raise_for_status()
                data = resp.json()["data"]
                # API may return items with explicit indexes; sort to preserve input order.
                return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]

            last_status = resp.status_code
            if attempt == MAX_ATTEMPTS - 1:
                break
            # honor Retry-After when given, otherwise exponential backoff + jitter
            retry_after = resp.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else 0.0
            except ValueError:
                delay = 0.0
            if delay <= 0:
                delay = BACKOFF_BASE_SECONDS * (2**attempt) * (1 + random.random() * 0.25)
            log.warning(
                "embeddings.retry", status=resp.status_code, attempt=attempt + 1, delay=round(delay, 2)
            )
            await asyncio.sleep(delay)

        raise EmbeddingRateLimitError(
            f"embedding provider returned {last_status} after {MAX_ATTEMPTS} attempts; "
            "the API rate limit is likely exhausted — wait a moment and retry"
        )


class CachedEmbeddingClient:
    """Redis read-through cache in front of a real client. Keyed on
    model+text hash, so identical texts never hit the provider twice."""

    def __init__(self, inner: EmbeddingClient, redis, model: str):
        self.inner = inner
        self.redis = redis
        self.model = model

    async def aclose(self) -> None:
        aclose = getattr(self.inner, "aclose", None)
        if aclose:
            await aclose()

    def _key(self, text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return f"emb:{self.model}:{digest}"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float] | None] = [None] * len(texts)
        misses: list[int] = []

        try:
            cached = await self.redis.mget([self._key(t) for t in texts])
        except Exception:
            cached = [None] * len(texts)  # cache down -> behave like no cache

        for index, hit in enumerate(cached):
            if hit is not None:
                vectors[index] = json.loads(hit)
            else:
                misses.append(index)

        if misses:
            fresh = await self.inner.embed_texts([texts[i] for i in misses])
            for index, vector in zip(misses, fresh):
                vectors[index] = vector
            try:
                pipe = self.redis.pipeline()
                for index in misses:
                    pipe.set(self._key(texts[index]), json.dumps(vectors[index]), ex=CACHE_TTL_SECONDS)
                await pipe.execute()
            except Exception:
                pass  # caching is best-effort

        return [v for v in vectors if v is not None]


def create_embedding_client(settings: Settings, redis=None) -> EmbeddingClient:
    # Test env always uses the fake so tests never call external APIs.
    if settings.APP_ENV == "test":
        return FakeEmbeddingClient(dim=settings.EMBEDDING_DIM)
    if settings.EMBEDDING_PROVIDER == "openai":
        client = OpenAIEmbeddingClient(settings)
        if redis is not None:
            return CachedEmbeddingClient(client, redis, settings.EMBEDDING_MODEL)
        return client
    raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")
