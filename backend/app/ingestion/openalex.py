import hashlib
import json
from typing import Any

import httpx
from redis.asyncio import Redis
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings

class OpenAlexError(RuntimeError):
    # custon error makes provider specific failures easy to log
    pass


class OpenAlexClient:
    base_url = "https://api.openalex.org"

    def __init__(self, settings: Settings, redis: Redis):
        # open alex asks clients to identify themselves for the polite pool

        if not settings.OPENALEX_MAILTO:
            raise OpenAlexError("OPENALX_MAILTO is required for the OpenAlex polite pool")
        
        self.mailto = settings.OPENALEX_MAILTO
        self.redis = redis

        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search_works(self, query: str, limit: int = 10) -> dict[str, Any]:
        #open alex search endpoint uses search and per-page

        params = {"search": query, "per-page": limit, "mailto": self.mailto}

        return await self._cached_get("/works", params=params, ttl_seconds=24*60*60)
    
    async def get_work(self, openalex_id: str) -> dict[str, Any]:
        
        work_id = openalex_id.rsplit("/", 1)[-1] # accepts full url or base id
        params = {"mailto": self.mailto}

        return await self._cached_get(
            f"/works/{work_id}", params=params, ttl_seconds=7*24*60*60
        )
    
    async def _cached_get(self, path: str, params: dict[str, Any], ttl_seconds:int) -> dict[str, Any]:
        # build a deterministic cache key from endpoints + params
        cache_key = self._cache_key(path, params)  
        # redis stored json strings: a cache hit skips the network entirely
        cached = await self.redis.get(cache_key)

        if cached:
            return json.loads(cached)
        
        data = await self._get(path, params)
        # store response eith ttl so development demos are fast and rate friendly

        await self.redis.set(cache_key, json.dumps(data), ex=ttl_seconds)

        return data
    
    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,   
    )
    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self.client.get(f"{self.base_url}{path}", params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            # these are transient failures; tenacity retries them
            resp.raise_for_status()
        if resp.status_code >= 400:
            # other 4xx errors usually mean bad input/config so fail immediately
            raise OpenAlexError(f"OpenAlex Request failed: {resp.status_code} {resp.text[:500]}")

        return resp.json()
    
    @staticmethod
    def _cached_key(path: str, params: dict[str, Any]) -> str:
        # sort keys so equivalent parameter dicts produce the same cache key
        payload = json.dumps({"path":path,"params":params}, sort_keys=True)

        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()

        return f"ext:openalex:{digest}"

        