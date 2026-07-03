# Module Guide: Ingestion

Files in this guide (all complete — type them as-is):

- `backend/app/ingestion/openalex.py`
- `backend/app/ingestion/crossref.py`
- `backend/app/ingestion/semantic_scholar.py`
- `backend/app/ingestion/normalize.py` ⭐ core learning file
- `backend/app/ingestion/upsert.py` ⭐ core learning file
- `backend/app/ingestion/bibtex.py`

**Why this module:** the hard part is not calling OpenAlex — it's making sure one real-world paper becomes exactly one row and one graph node, no matter how many sources it arrives from. That's entity resolution: normalize identifiers, match in a strict priority order, enrich in place, never insert a duplicate. Plus the **stub rule**: every reference becomes a placeholder row immediately, so citation edges exist from the very first import.

Note: `upsert.py` imports `build_title_abstract_chunk` from `app/retrieval/chunking.py` (guide 04) — it's a 25-line pure function; type it first when you hit the import.

**Comment style:** ingestion is where most "why" bugs happen, so the snippets include extra comments around caching, dedup, and stub creation.

---

## `backend/app/ingestion/openalex.py`

Polite-pool `mailto` is mandatory (client refuses to construct without it), every GET goes through a Redis cache (searches 24h, work details 7d — demos become instant and rate limits stop mattering), tenacity retries 429/5xx with exponential backoff.

```python
# hashlib turns request parameters into short stable cache-key digests.
import hashlib
# json serializes cached API payloads into Redis strings.
import json
# Any is used because external API JSON is untyped at the boundary.
from typing import Any

# httpx is the async HTTP client used across external providers.
import httpx
# Redis stores cached API responses so demos avoid repeated network calls.
from redis.asyncio import Redis
# tenacity retries transient provider failures such as 429 and 5xx.
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Settings supplies mailto/config; no env reads here.
from app.config import Settings


class OpenAlexError(RuntimeError):
    # Custom error makes provider-specific failures easy to catch/log.
    pass


class OpenAlexClient:
    # Base API URL shared by search and detail requests.
    base_url = "https://api.openalex.org"

    def __init__(self, settings: Settings, redis: Redis):
        # OpenAlex asks clients to identify themselves for the polite pool.
        if not settings.OPENALEX_MAILTO:
            raise OpenAlexError("OPENALEX_MAILTO is required for the OpenAlex polite pool")
        # Store mailto so every request can include it.
        self.mailto = settings.OPENALEX_MAILTO
        # Redis client is injected from app lifespan/worker setup.
        self.redis = redis
        # One reusable AsyncClient per OpenAlexClient.
        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self) -> None:
        # Close HTTP connections when the owning app/worker shuts down.
        await self.client.aclose()

    async def search_works(self, query: str, limit: int = 10) -> dict[str, Any]:
        # OpenAlex search endpoint uses `search` and `per-page`.
        params = {"search": query, "per-page": limit, "mailto": self.mailto}
        # Searches change more often, so cache for 24 hours.
        return await self._cached_get("/works", params=params, ttl_seconds=24 * 60 * 60)

    async def get_work(self, openalex_id: str) -> dict[str, Any]:
        # Accept both `https://openalex.org/W...` and bare `W...` identifiers.
        work_id = openalex_id.rsplit("/", 1)[-1]   # accepts full URL or bare W-id
        params = {"mailto": self.mailto}
        # Work details are stable enough to cache for a week.
        return await self._cached_get(
            f"/works/{work_id}", params=params, ttl_seconds=7 * 24 * 60 * 60
        )

    async def _cached_get(self, path: str, params: dict[str, Any], ttl_seconds: int) -> dict[str, Any]:
        # Build a deterministic cache key from endpoint + params.
        cache_key = self._cache_key(path, params)
        # Redis stores JSON strings; a cache hit skips the network entirely.
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)
        # Cache miss: do the real HTTP request.
        data = await self._get(path, params)
        # Store response with TTL so development demos are fast and rate-limit friendly.
        await self.redis.set(cache_key, json.dumps(data), ex=ttl_seconds)
        return data

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        # Compose full OpenAlex URL and pass query params separately for safe encoding.
        resp = await self.client.get(f"{self.base_url}{path}", params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            # These are transient failures; tenacity retries them.
            resp.raise_for_status()          # retried by tenacity
        if resp.status_code >= 400:
            # Other 4xx errors usually mean bad input/config, so fail immediately.
            raise OpenAlexError(f"OpenAlex request failed: {resp.status_code} {resp.text[:500]}")
        # Boundary output is raw provider JSON; normalize.py converts it later.
        return resp.json()

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any]) -> str:
        # Sort keys so equivalent parameter dicts produce the same cache key.
        payload = json.dumps({"path": path, "params": params}, sort_keys=True)
        # SHA-1 is fine for cache keys; this is not security-sensitive.
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        # Namespaced key makes Redis easy to inspect/debug.
        return f"ext:openalex:{digest}"
```

Walkthrough:

- External clients return raw JSON; they never write to the database.
- Redis caching belongs here because callers should not care whether a request came from cache.
- `mailto` is both etiquette and reliability: OpenAlex gives identified clients better behavior.

## `backend/app/ingestion/crossref.py`

BibTeX via **DOI content negotiation**: `GET https://doi.org/{doi}` with `Accept: application/x-bibtex`. Publisher entries have correct fields and capitalization protection — always preferred over hand-rolled generation.

```python
# Hash DOI into a compact cache key.
import hashlib

# Async HTTP client.
import httpx
# Redis cache for BibTeX responses.
from redis.asyncio import Redis

# Settings supplies Crossref mailto.
from app.config import Settings


class CrossrefClient:
    def __init__(self, settings: Settings, redis: Redis):
        # Crossref wants contact info in User-Agent.
        self.mailto = settings.CROSSREF_MAILTO
        # Shared Redis client.
        self.redis = redis
        # Reusable HTTP client.
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
```

Walkthrough:

- Crossref/DOI BibTeX is preferred because publisher metadata is usually more complete.
- Returning `None` is intentional: BibTeX fallback generation is not an exceptional path.

## `backend/app/ingestion/semantic_scholar.py`

The anonymous S2 pool is shared and tiny (~100 req/5 min globally) — never rely on it. Clean no-op without an API key.

```python
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
```

## ⭐ `backend/app/ingestion/normalize.py`

Every source converges into `NormalizedPaper` before touching storage. Two normalizers carry the whole dedup story:

- **DOIs** are case-insensitive by spec and arrive with/without the `https://doi.org/` prefix — the `papers.doi` UNIQUE constraint is meaningless without normalizing first.
- **OpenAlex abstracts** arrive as an inverted index (`word -> [positions]`) and must be reconstructed.

```python
# Regex is used for DOI and title normalization.
import re

# BaseModel gives typed DTOs; Field(default_factory=list) prevents shared mutable defaults.
from pydantic import BaseModel, Field


class NormalizedAuthor(BaseModel):
    # External provider ID if known (OpenAlex author URL, S2 author ID, etc.).
    source_id: str | None = None
    # Human-readable author name.
    name: str
    # Authorship order on the paper; useful for BibTeX first-author keys.
    order: int | None = None


class NormalizedConcept(BaseModel):
    # Normalized concept/topic/method name.
    name: str
    # MVP defaults to generic concept; future values include method/dataset/task.
    type: str = "concept"
    # Provider confidence/relevance score.
    score: float | None = None
    # Where the concept came from, e.g. openalex.
    source: str


class NormalizedPaper(BaseModel):
    source: str                      # 'openalex' | 'semantic_scholar' | 'crossref'
    source_id: str
    title: str | None = None
    doi: str | None = None           # already normalized
    abstract: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    venue_name: str | None = None
    cited_by_count: int | None = None
    url: str | None = None
    pdf_url: str | None = None
    authors: list[NormalizedAuthor] = Field(default_factory=list)
    concepts: list[NormalizedConcept] = Field(default_factory=list)
    reference_source_ids: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


def normalize_doi(raw: str | None) -> str | None:
    """Apply before ANY read or write of a DOI."""
    if not raw:
        # Treat empty/missing DOI as no DOI.
        return None
    # Remove surrounding whitespace.
    doi = raw.strip()
    # Strip common DOI URL prefixes.
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    # DOI matching is case-insensitive, so store lowercase.
    return doi.lower() or None


def normalize_title_for_match(title: str | None) -> str | None:
    """Lowercase, alphanumeric-only, collapsed whitespace — the last-resort dedup key."""
    if not title:
        return None
    # Convert punctuation/dashes/etc. to spaces and lowercase.
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    # Empty string after normalization means there is no usable title key.
    return normalized or None


def reconstruct_openalex_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    # OpenAlex stores word -> positions; flatten into (position, word).
    positions = [(i, word) for word, idxs in inv.items() for i in idxs]
    # Sort by position to recover the original abstract text.
    return " ".join(word for _, word in sorted(positions))


def _openalex_authors(work: dict) -> list[NormalizedAuthor]:
    # Convert OpenAlex authorships into normalized authors.
    authors: list[NormalizedAuthor] = []
    for order, authorship in enumerate(work.get("authorships") or [], start=1):
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(NormalizedAuthor(source_id=author.get("id"), name=name, order=order))
    return authors


def _openalex_concepts(work: dict) -> list[NormalizedConcept]:
    # Convert OpenAlex concepts/topics into normalized concept DTOs.
    concepts: list[NormalizedConcept] = []
    for concept in work.get("concepts") or []:
        name = concept.get("display_name")
        if name:
            concepts.append(
                NormalizedConcept(name=name, score=concept.get("score"), source="openalex")
            )
    if not concepts:  # newer OpenAlex records use topics instead of concepts
        for topic in work.get("topics") or []:
            name = topic.get("display_name")
            if name:
                concepts.append(
                    NormalizedConcept(name=name, score=topic.get("score"), source="openalex")
                )
    return concepts[:10]


def normalize_openalex_work(work: dict) -> NormalizedPaper:
    # Defensive `or {}` handles OpenAlex null sub-objects.
    primary_location = work.get("primary_location") or {}
    location_source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    # Return one provider-neutral DTO; storage code never sees raw provider shapes.
    return NormalizedPaper(
        source="openalex",
        source_id=work["id"],
        title=work.get("display_name") or work.get("title"),
        doi=normalize_doi(work.get("doi")),
        abstract=reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
        publication_year=work.get("publication_year"),
        publication_date=work.get("publication_date"),
        venue_name=location_source.get("display_name"),
        cited_by_count=work.get("cited_by_count"),
        url=work["id"],
        pdf_url=open_access.get("oa_url"),
        authors=_openalex_authors(work),
        concepts=_openalex_concepts(work),
        reference_source_ids=list(dict.fromkeys(work.get("referenced_works") or [])),
        raw=work,
    )
```

(`dict.fromkeys(...)` dedupes references while preserving order. The defensive `or {}` chains matter — OpenAlex nulls out whole sub-objects freely.)

Normalization walkthrough:

- DTOs decouple external APIs from database writes.
- `normalize_doi()` must run before both lookup and insert, or the unique DOI constraint will not protect you.
- `normalize_title_for_match()` is intentionally last-resort because titles can vary across providers.
- OpenAlex abstracts are inverted indexes, not plain strings.
- `reference_source_ids` are raw OpenAlex work IDs used to create stubs and citation edges.

## ⭐ `backend/app/ingestion/upsert.py`

The dedup match order (first hit wins): **normalized DOI → openalex_id → semantic_scholar_id → normalized title + year**. On match, *enrich the existing row* (fill nulls, refresh `cited_by_count`, flip `is_stub` off) — the UUID and every citation edge survive. On no match, insert.

The stub rule: every referenced work is upserted as a bare `is_stub=true` row and citation edges are inserted immediately. Without stubs, co-citation and bibliographic coupling return nothing.

```python
# Future annotations help with type hints and forward refs.
from __future__ import annotations

# date converts ISO publication_date strings to Python dates.
from datetime import date
# UUID is used for project/paper identities.
from uuid import UUID

# select reads existing rows; pg_insert enables ON CONFLICT helpers.
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
# AsyncSession is the current DB unit of work.
from sqlalchemy.ext.asyncio import AsyncSession

# ORM tables this module writes.
from app.db.models import (
    Author,
    Citation,
    Concept,
    Paper,
    PaperAuthor,
    PaperChunk,
    PaperConcept,
    ProjectPaper,
)
# BibTeX helpers generate project-local citation keys.
from app.ingestion.bibtex import BibtexPaper, generate_bibtex_key
# Normalized DTOs are the only accepted input shape.
from app.ingestion.normalize import NormalizedAuthor, NormalizedConcept, NormalizedPaper, normalize_title_for_match
# Structured logging.
from app.logging import get_logger
# Chunking creates the single MVP title+abstract chunk after paper upsert.
from app.retrieval.chunking import build_title_abstract_chunk

# Module logger.
log = get_logger(__name__)


async def find_existing_paper(session: AsyncSession, np: NormalizedPaper) -> Paper | None:
    # Best match: DOI, because it is cross-provider and normalized.
    if np.doi:
        paper = (
            await session.execute(select(Paper).where(Paper.doi == np.doi))
        ).scalar_one_or_none()
        if paper:
            return paper
    if np.source == "openalex":
        # Next best: provider-specific ID for the current source.
        paper = (
            await session.execute(select(Paper).where(Paper.openalex_id == np.source_id))
        ).scalar_one_or_none()
        if paper:
            return paper
    if np.source == "semantic_scholar":
        # Same idea for Semantic Scholar imports/enrichment.
        paper = (
            await session.execute(select(Paper).where(Paper.semantic_scholar_id == np.source_id))
        ).scalar_one_or_none()
        if paper:
            return paper
    # Last resort: normalized title + year (year-scoped, compared in Python).
    match_title = normalize_title_for_match(np.title)
    if match_title and np.publication_year:
        candidates = (
            await session.execute(
                select(Paper).where(
                    Paper.publication_year == np.publication_year,
                    Paper.title.is_not(None),
                )
            )
        ).scalars()
        for candidate in candidates:
            if normalize_title_for_match(candidate.title) == match_title:
                return candidate
    return None


def _enrich(paper: Paper, np: NormalizedPaper) -> None:
    """Fill nulls, refresh volatile fields, never downgrade existing data."""
    if np.source == "openalex" and paper.openalex_id is None:
        paper.openalex_id = np.source_id
    if np.source == "semantic_scholar" and paper.semantic_scholar_id is None:
        paper.semantic_scholar_id = np.source_id
    if paper.doi is None and np.doi:
        paper.doi = np.doi
    if paper.title is None and np.title:
        paper.title = np.title
    if paper.abstract is None and np.abstract:
        paper.abstract = np.abstract
    if paper.publication_year is None:
        paper.publication_year = np.publication_year
    if paper.publication_date is None and np.publication_date:
        try:
            paper.publication_date = date.fromisoformat(np.publication_date)
        except ValueError:
            pass
    if paper.venue_name is None:
        paper.venue_name = np.venue_name
    if paper.url is None:
        paper.url = np.url
    if paper.pdf_url is None:
        paper.pdf_url = np.pdf_url
    if np.cited_by_count is not None:
        paper.cited_by_count = np.cited_by_count
    paper.is_stub = False


async def _upsert_author(session: AsyncSession, na: NormalizedAuthor) -> Author:
    # Prefer matching authors by provider ID when available.
    if na.source_id:
        author = (
            await session.execute(select(Author).where(Author.openalex_id == na.source_id))
        ).scalar_one_or_none()
        if author:
            return author
    author = (
        # Fallback by name is imperfect but acceptable for POC metadata.
        await session.execute(select(Author).where(Author.name == na.name))
    ).scalars().first()
    if author:
        if author.openalex_id is None and na.source_id:
            author.openalex_id = na.source_id
        return author
    author = Author(openalex_id=na.source_id, name=na.name)
    session.add(author)
    await session.flush()
    return author


async def _link_authors(session: AsyncSession, paper: Paper, authors: list[NormalizedAuthor]) -> None:
    # Link each normalized author to the paper.
    for na in authors:
        author = await _upsert_author(session, na)
        await session.execute(
            pg_insert(PaperAuthor)
            .values(paper_id=paper.id, author_id=author.id, author_order=na.order)
            .on_conflict_do_nothing(index_elements=["paper_id", "author_id"])
        )


async def _link_concepts(session: AsyncSession, paper: Paper, concepts: list[NormalizedConcept]) -> None:
    # Concepts are normalized by name.
    for nc in concepts:
        concept = (
            await session.execute(select(Concept).where(Concept.name == nc.name))
        ).scalar_one_or_none()
        if concept is None:
            concept = Concept(name=nc.name, type=nc.type)
            session.add(concept)
            await session.flush()
        await session.execute(
            pg_insert(PaperConcept)
            .values(paper_id=paper.id, concept_id=concept.id, score=nc.score, source=nc.source)
            .on_conflict_do_nothing(index_elements=["paper_id", "concept_id"])
        )


async def upsert_paper(session: AsyncSession, np: NormalizedPaper) -> Paper:
    # Try dedup match before inserting.
    paper = await find_existing_paper(session, np)
    created = paper is None
    if paper is None:
        # New canonical paper row.
        paper = Paper(is_stub=False)
        session.add(paper)
    _enrich(paper, np)
    # Flush assigns UUIDs before link tables reference the paper.
    await session.flush()
    await _link_authors(session, paper, np.authors)
    await _link_concepts(session, paper, np.concepts)
    log.info("paper.upsert", paper_id=str(paper.id), created=created, source=np.source)
    return paper


async def upsert_references_as_stubs(
    session: AsyncSession, citing: Paper, reference_source_ids: list[str]
) -> list[Paper]:
    """Create bare is_stub rows for unknown references and idempotent citation edges.

    Returns every cited Paper row (stub or full) so the caller can mirror them to Neo4j.
    """
    refs = [r for r in dict.fromkeys(reference_source_ids) if r]
    if not refs:
        return []
    existing = {
        p.openalex_id: p
        for p in (
            await session.execute(select(Paper).where(Paper.openalex_id.in_(refs)))
        ).scalars()
    }
    new_stubs = [Paper(openalex_id=ref, is_stub=True) for ref in refs if ref not in existing]
    # Add unknown references as placeholder papers.
    session.add_all(new_stubs)
    await session.flush()

    cited = list(existing.values()) + new_stubs
    # Create directed citation edges from the imported paper to every reference.
    edge_values = [
        {"citing_paper_id": citing.id, "cited_paper_id": p.id} for p in cited if p.id != citing.id
    ]
    if edge_values:
        await session.execute(
            pg_insert(Citation)
            .values(edge_values)
            .on_conflict_do_nothing(index_elements=["citing_paper_id", "cited_paper_id"])
        )
    log.info("paper.stubs", citing_id=str(citing.id), stubs_created=len(new_stubs), edges=len(edge_values))
    return cited


async def create_title_abstract_chunk(session: AsyncSession, paper: Paper) -> None:
    # Build one semantic chunk from whatever title/abstract data exists.
    chunk = build_title_abstract_chunk(paper.title, paper.abstract)
    if chunk is None:
        return
    existing = (
        await session.execute(
            select(PaperChunk).where(PaperChunk.paper_id == paper.id, PaperChunk.chunk_index == 0)
        )
    ).scalar_one_or_none()
    if existing:
        if existing.text != chunk.text:      # e.g. stub promoted: abstract arrived
            existing.text = chunk.text
            existing.token_count = chunk.token_count
            existing.embedding = None        # force re-embed
        return
    session.add(
        PaperChunk(
            paper_id=paper.id,
            chunk_index=0,
            section=chunk.section,
            text=chunk.text,
            token_count=chunk.token_count,
        )
    )


async def link_project_paper(session: AsyncSession, project_id: UUID, paper: Paper) -> str:
    """Attach a paper to a project with a stable, collision-free BibTeX key."""
    existing = (
        await session.execute(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id, ProjectPaper.paper_id == paper.id
            )
        )
    ).scalar_one_or_none()
    if existing:
        # Reuse stable key if the paper is already in this project.
        return existing.bibtex_key

    author_names = [
        row[0]
        for row in (
            await session.execute(
                select(Author.name)
                .join(PaperAuthor, PaperAuthor.author_id == Author.id)
                .where(PaperAuthor.paper_id == paper.id)
                .order_by(PaperAuthor.author_order)
            )
        ).all()
    ]
    existing_keys = {
        row[0]
        for row in (
            await session.execute(
                select(ProjectPaper.bibtex_key).where(ProjectPaper.project_id == project_id)
            )
        ).all()
    }
    key = generate_bibtex_key(
        BibtexPaper(
            title=paper.title,
            publication_year=paper.publication_year,
            venue_name=paper.venue_name,
            doi=paper.doi,
            url=paper.url,
            authors=author_names,
        ),
        existing_keys,
    )
    session.add(ProjectPaper(project_id=project_id, paper_id=paper.id, bibtex_key=key))
    await session.flush()
    return key


async def ingest_normalized_paper(
    session: AsyncSession, np: NormalizedPaper
) -> tuple[Paper, list[Paper]]:
    """Upsert paper + stub references + chunk. Project linking is separate on
    purpose — stub promotion enriches a paper without adding it to any project."""
    paper = await upsert_paper(session, np)
    cited = await upsert_references_as_stubs(session, paper, np.reference_source_ids)
    await create_title_abstract_chunk(session, paper)
    return paper, cited
```

Upsert walkthrough:

- `find_existing_paper()` is the entity-resolution gate; all imports go through it.
- `_enrich()` promotes stubs and fills missing fields without downgrading existing metadata.
- `_link_authors()` and `_link_concepts()` make normalized many-to-many rows idempotently.
- `upsert_references_as_stubs()` is what makes the citation graph non-empty immediately.
- `create_title_abstract_chunk()` prepares retrieval input while keeping embeddings nullable until the embed job runs.
- `link_project_paper()` is project-specific; importing metadata and adding to a project are separate concerns.

## `backend/app/ingestion/bibtex.py`

Fallback generator for papers without a DOI, plus key generation and re-keying. The non-negotiable part: **escape LaTeX specials in every field** — one raw `&` in a title breaks compilation three steps away from the cause.

```python
# Regex handles key parsing and acronym protection.
import re
# unicodedata strips accents for ASCII-safe citation keys.
import unicodedata
# dataclass gives a tiny typed input object.
from dataclasses import dataclass

# Mapping of LaTeX special chars to safe escaped text.
LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class BibtexPaper:
    # Minimal paper shape needed to generate keys and fallback BibTeX.
    title: str | None
    publication_year: int | None
    venue_name: str | None
    doi: str | None
    url: str | None
    authors: list[str]


def latex_escape(value: str) -> str:
    # Replace every special character, leave ordinary characters unchanged.
    return "".join(LATEX_ESCAPES.get(ch, ch) for ch in value)


def ascii_slug(value: str) -> str:
    # Strip accents, lowercase, remove non-alphanumerics.
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", normalized.lower())


def first_title_word(title: str | None) -> str:
    # Used in keys like lewis2020retrieval.
    if not title:
        return "paper"
    for word in re.findall(r"[A-Za-z0-9]+", title):
        slug = ascii_slug(word)
        if slug:
            return slug
    return "paper"


def protect_acronyms(title: str) -> str:
    """Brace-protect ALL-CAPS tokens so BibTeX styles don't lowercase them."""
    return re.sub(r"\b([A-Z]{2,}[A-Za-z0-9-]*)\b", r"{\1}", title)


def generate_bibtex_key(paper: BibtexPaper, existing_keys: set[str]) -> str:
    """{firstauthorlastname}{year}{firsttitleword}, lowercase ASCII; collisions
    append a, b, c within the project."""
    last_name = "unknown"
    if paper.authors:
        last_name = ascii_slug(paper.authors[0].split()[-1]) or "unknown"
    year = str(paper.publication_year or "nd")
    base = f"{last_name}{year}{first_title_word(paper.title)}"
    key = base
    suffix_ord = ord("a")
    while key in existing_keys:
        # Collision handling: key, keya, keyb, ...
        key = f"{base}{chr(suffix_ord)}"
        suffix_ord += 1
    return key


def rekey_bibtex(bibtex: str, new_key: str) -> str:
    """Swap the entry key of the first BibTeX entry (Crossref returns its own key;
    the entry must match the key we put into \\cite{...})."""
    return re.sub(r"^(\s*@\w+\s*\{)[^,\n]*", lambda m: m.group(1) + new_key, bibtex, count=1)


def generate_fallback_bibtex(key: str, paper: BibtexPaper) -> str:
    # Build only fields we actually know.
    fields: list[tuple[str, str]] = []
    if paper.title:
        fields.append(("title", protect_acronyms(latex_escape(paper.title))))
    if paper.authors:
        fields.append(("author", " and ".join(latex_escape(a) for a in paper.authors)))
    if paper.publication_year:
        fields.append(("year", str(paper.publication_year)))
    if paper.venue_name:
        fields.append(("journal", latex_escape(paper.venue_name)))
    if paper.doi:
        fields.append(("doi", latex_escape(paper.doi)))
    if paper.url:
        fields.append(("url", latex_escape(paper.url)))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@article{{{key},\n{body}\n}}\n"
```

BibTeX walkthrough:

- Citation keys are project-local, so collisions are checked against `existing_keys`.
- Crossref BibTeX gets re-keyed so `\cite{key}` matches `references.bib`.
- Fallback generation escapes every field because LaTeX failures from raw special characters are painful to debug.

## Acceptance checks

```bash
docker compose exec backend pytest app/tests/test_normalize.py app/tests/test_bibtex.py
```

(Complete test files are in guide 09.) Behavior that must hold:

- DOI variants (`https://doi.org/10.1/X`, `http://dx.doi.org/10.1/x`, ` 10.1/X `) → one string.
- Inverted abstract reconstructs in position order.
- Importing the same paper by DOI and by OpenAlex ID yields **one** row (dedup).
- Every reference gets a stub row + a citation edge; re-import is a no-op.
- A stub that gets fully imported later is enriched **in place** — same UUID, edges survive, `is_stub` flips false.
- Hostile title `P&L of Q&A systems: 100% _better_` produces compilable BibTeX.
