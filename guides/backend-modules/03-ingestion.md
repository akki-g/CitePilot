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

---

## `backend/app/ingestion/openalex.py`

Polite-pool `mailto` is mandatory (client refuses to construct without it), every GET goes through a Redis cache (searches 24h, work details 7d — demos become instant and rate limits stop mattering), tenacity retries 429/5xx with exponential backoff.

```python
import hashlib
import json
from typing import Any

import httpx
from redis.asyncio import Redis
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings


class OpenAlexError(RuntimeError):
    pass


class OpenAlexClient:
    base_url = "https://api.openalex.org"

    def __init__(self, settings: Settings, redis: Redis):
        if not settings.OPENALEX_MAILTO:
            raise OpenAlexError("OPENALEX_MAILTO is required for the OpenAlex polite pool")
        self.mailto = settings.OPENALEX_MAILTO
        self.redis = redis
        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search_works(self, query: str, limit: int = 10) -> dict[str, Any]:
        params = {"search": query, "per-page": limit, "mailto": self.mailto}
        return await self._cached_get("/works", params=params, ttl_seconds=24 * 60 * 60)

    async def get_work(self, openalex_id: str) -> dict[str, Any]:
        work_id = openalex_id.rsplit("/", 1)[-1]   # accepts full URL or bare W-id
        params = {"mailto": self.mailto}
        return await self._cached_get(
            f"/works/{work_id}", params=params, ttl_seconds=7 * 24 * 60 * 60
        )

    async def _cached_get(self, path: str, params: dict[str, Any], ttl_seconds: int) -> dict[str, Any]:
        cache_key = self._cache_key(path, params)
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)
        data = await self._get(path, params)
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
            resp.raise_for_status()          # retried by tenacity
        if resp.status_code >= 400:
            raise OpenAlexError(f"OpenAlex request failed: {resp.status_code} {resp.text[:500]}")
        return resp.json()

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any]) -> str:
        payload = json.dumps({"path": path, "params": params}, sort_keys=True)
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return f"ext:openalex:{digest}"
```

## `backend/app/ingestion/crossref.py`

BibTeX via **DOI content negotiation**: `GET https://doi.org/{doi}` with `Accept: application/x-bibtex`. Publisher entries have correct fields and capitalization protection — always preferred over hand-rolled generation.

```python
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
        cache_key = f"ext:crossref:bibtex:{hashlib.sha1(doi.encode()).hexdigest()}"
        cached = await self.redis.get(cache_key)
        if cached:
            return cached
        headers = {
            "Accept": "application/x-bibtex",
            "User-Agent": f"CitePilot/0.1 (mailto:{self.mailto})",
        }
        resp = await self.client.get(
            f"https://doi.org/{doi}", headers=headers, follow_redirects=True
        )
        if resp.status_code >= 400 or not resp.text.strip().startswith("@"):
            return None
        await self.redis.set(cache_key, resp.text, ex=7 * 24 * 60 * 60)
        return resp.text
```

## `backend/app/ingestion/semantic_scholar.py`

The anonymous S2 pool is shared and tiny (~100 req/5 min globally) — never rely on it. Clean no-op without an API key.

```python
from typing import Any

import httpx

from app.config import Settings


class SemanticScholarClient:
    base_url = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, settings: Settings):
        self.api_key = settings.SEMANTIC_SCHOLAR_API_KEY
        self.client = httpx.AsyncClient(timeout=20)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        headers = {"x-api-key": self.api_key}
        params = {"fields": "title,abstract,authors,year,venue,citationCount,fieldsOfStudy,tldr"}
        resp = await self.client.get(
            f"{self.base_url}/paper/{paper_id}", headers=headers, params=params
        )
        if resp.status_code >= 400:
            return None
        return resp.json()
```

## ⭐ `backend/app/ingestion/normalize.py`

Every source converges into `NormalizedPaper` before touching storage. Two normalizers carry the whole dedup story:

- **DOIs** are case-insensitive by spec and arrive with/without the `https://doi.org/` prefix — the `papers.doi` UNIQUE constraint is meaningless without normalizing first.
- **OpenAlex abstracts** arrive as an inverted index (`word -> [positions]`) and must be reconstructed.

```python
import re

from pydantic import BaseModel, Field


class NormalizedAuthor(BaseModel):
    source_id: str | None = None
    name: str
    order: int | None = None


class NormalizedConcept(BaseModel):
    name: str
    type: str = "concept"
    score: float | None = None
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
        return None
    doi = raw.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return doi.lower() or None


def normalize_title_for_match(title: str | None) -> str | None:
    """Lowercase, alphanumeric-only, collapsed whitespace — the last-resort dedup key."""
    if not title:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return normalized or None


def reconstruct_openalex_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    positions = [(i, word) for word, idxs in inv.items() for i in idxs]
    return " ".join(word for _, word in sorted(positions))


def _openalex_authors(work: dict) -> list[NormalizedAuthor]:
    authors: list[NormalizedAuthor] = []
    for order, authorship in enumerate(work.get("authorships") or [], start=1):
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(NormalizedAuthor(source_id=author.get("id"), name=name, order=order))
    return authors


def _openalex_concepts(work: dict) -> list[NormalizedConcept]:
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
    primary_location = work.get("primary_location") or {}
    location_source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
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

## ⭐ `backend/app/ingestion/upsert.py`

The dedup match order (first hit wins): **normalized DOI → openalex_id → semantic_scholar_id → normalized title + year**. On match, *enrich the existing row* (fill nulls, refresh `cited_by_count`, flip `is_stub` off) — the UUID and every citation edge survive. On no match, insert.

The stub rule: every referenced work is upserted as a bare `is_stub=true` row and citation edges are inserted immediately. Without stubs, co-citation and bibliographic coupling return nothing.

```python
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.ingestion.bibtex import BibtexPaper, generate_bibtex_key
from app.ingestion.normalize import NormalizedAuthor, NormalizedConcept, NormalizedPaper, normalize_title_for_match
from app.logging import get_logger
from app.retrieval.chunking import build_title_abstract_chunk

log = get_logger(__name__)


async def find_existing_paper(session: AsyncSession, np: NormalizedPaper) -> Paper | None:
    if np.doi:
        paper = (
            await session.execute(select(Paper).where(Paper.doi == np.doi))
        ).scalar_one_or_none()
        if paper:
            return paper
    if np.source == "openalex":
        paper = (
            await session.execute(select(Paper).where(Paper.openalex_id == np.source_id))
        ).scalar_one_or_none()
        if paper:
            return paper
    if np.source == "semantic_scholar":
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
    if na.source_id:
        author = (
            await session.execute(select(Author).where(Author.openalex_id == na.source_id))
        ).scalar_one_or_none()
        if author:
            return author
    author = (
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
    for na in authors:
        author = await _upsert_author(session, na)
        await session.execute(
            pg_insert(PaperAuthor)
            .values(paper_id=paper.id, author_id=author.id, author_order=na.order)
            .on_conflict_do_nothing(index_elements=["paper_id", "author_id"])
        )


async def _link_concepts(session: AsyncSession, paper: Paper, concepts: list[NormalizedConcept]) -> None:
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
    paper = await find_existing_paper(session, np)
    created = paper is None
    if paper is None:
        paper = Paper(is_stub=False)
        session.add(paper)
    _enrich(paper, np)
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
    session.add_all(new_stubs)
    await session.flush()

    cited = list(existing.values()) + new_stubs
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

## `backend/app/ingestion/bibtex.py`

Fallback generator for papers without a DOI, plus key generation and re-keying. The non-negotiable part: **escape LaTeX specials in every field** — one raw `&` in a title breaks compilation three steps away from the cause.

```python
import re
import unicodedata
from dataclasses import dataclass

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
    title: str | None
    publication_year: int | None
    venue_name: str | None
    doi: str | None
    url: str | None
    authors: list[str]


def latex_escape(value: str) -> str:
    return "".join(LATEX_ESCAPES.get(ch, ch) for ch in value)


def ascii_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", normalized.lower())


def first_title_word(title: str | None) -> str:
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
        key = f"{base}{chr(suffix_ord)}"
        suffix_ord += 1
    return key


def rekey_bibtex(bibtex: str, new_key: str) -> str:
    """Swap the entry key of the first BibTeX entry (Crossref returns its own key;
    the entry must match the key we put into \\cite{...})."""
    return re.sub(r"^(\s*@\w+\s*\{)[^,\n]*", lambda m: m.group(1) + new_key, bibtex, count=1)


def generate_fallback_bibtex(key: str, paper: BibtexPaper) -> str:
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
