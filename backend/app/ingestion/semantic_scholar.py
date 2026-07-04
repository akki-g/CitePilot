# External API JSON shape is not typed, so Any is acceptable at the boundary.
from typing import Any

# Async HTTP client.
import httpx

# Settings supplies optional API key.
from app.config import Settings


class SemanticScholarClient:
    # Semantic Scholar Graph API base URL.
    base_url = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, settings: Settings):
        # Empty key means enrichment is disabled.
        self.api_key = settings.SEMANTIC_SCHOLAR_API_KEY
        # Reusable HTTP client.
        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        if not self.api_key:
            # No-op keeps the MVP reliable without relying on the tiny anonymous pool.
            return None
        # API key goes in x-api-key per S2 docs.
        headers = {"x-api-key": self.api_key}
        # Request only enrichment fields the app can use.
        params = {"fields": "title,abstract,authors,year,venue,citationCount,fieldsOfStudy,tldr"}
        resp = await self.client.get(
            f"{self.base_url}/paper/{paper_id}", headers=headers, params=params
        )
        if resp.status_code >= 400:
            # Enrichment should not break import; fail soft.
            return None
        return resp.json()