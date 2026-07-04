import hashlib 
import httpx 
from redis.asyncio import Redis

from app.config import Settings


class CrossrefClient:
    def __init__(self, settings: Settings, redis: Redis):
        self.mailto = settings.CROSSREF_MAILTO
        self.redis = redis
        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get_bibtex(self, doi: str) -> str | None:
        # DOI is already normalized before this function is called.
        cache_key = f"ext:crossref:bibtex:{hashlib.sha1(doi.encode()).hexdigest()}"
        cached = await self.redis.get(cache_key)
        if cached:
            return cached
        # Content negotiation asks doi.org/Crossref for BibTeX instead of JSON.
        headers = {
            "Accept": "application/x-bibtex",
            "User-Agent": f"CitePilot/0.1 (mailto:{self.mailto})",
        }
        resp = await self.client.get(
            f"https://doi.org/{doi}", headers=headers, follow_redirects=True
        )
        if resp.status_code >= 400 or not resp.text.strip().startswith("@"):
            # Not every DOI resolves to BibTeX; fallback generator handles this.
            return None
        # Cache successful publisher-quality BibTeX for a week.
        await self.redis.set(cache_key, resp.text, ex=7 * 24 * 60 * 60)
        return resp.text
  