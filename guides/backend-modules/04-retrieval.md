# Module Guide: Retrieval

Files in this guide (all complete — type them as-is):

- `backend/app/retrieval/chunking.py`
- `backend/app/retrieval/embeddings.py`
- `backend/app/retrieval/vector_search.py`
- `backend/app/retrieval/graph_search.py`
- `backend/app/retrieval/fusion.py` ⭐ core learning file
- `backend/app/retrieval/hybrid.py` ⭐ core learning file
- `backend/app/retrieval/explain.py`

**Why this module:** the technical heart of the project. Five independent ranked lists (one semantic, four graph signals) fused with Reciprocal Rank Fusion, hydrated with feature-derived explanations. Each signal is individually debuggable; the fusion is three lines of math; no result is ever a bare score.

The interview one-liner: *vector search answers "what text is similar?", the graph answers "what is structurally related?" — and the papers you must cite are often structurally related without being textually similar.*

---

## `backend/app/retrieval/chunking.py`

One chunk per paper: `title + abstract`. Deliberately **no** synthetic concept/citation-summary chunks — template text clusters with other template text and pollutes top-k, and concept overlap is already a graph signal; encoding it in vector space would double-count it at fusion time.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    section: str
    text: str
    token_count: int | None = None


def build_title_abstract_chunk(title: str | None, abstract: str | None) -> Chunk | None:
    parts = [part.strip() for part in [title, abstract] if part and part.strip()]
    if not parts:
        return None  # bare stub: nothing to embed yet
    text = "\n\n".join(parts)
    return Chunk(
        chunk_index=0,
        section="title_abstract",
        text=text,
        token_count=max(1, len(text.split())),  # word count as a cheap proxy
    )
```

## `backend/app/retrieval/embeddings.py`

Provider-agnostic interface + one real provider + a deterministic fake. The fake is hash-seeded so vector tests are stable and never call an API.

```python
import hashlib
import random
from typing import Protocol

import httpx

from app.config import Settings


class EmbeddingClient(Protocol):
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbeddingClient:
    """Deterministic pseudo-random vectors keyed on the text's hash."""

    def __init__(self, dim: int = 1536):
        self.dim = dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            vectors.append([rng.uniform(-1.0, 1.0) for _ in range(self.dim)])
        return vectors


class OpenAIEmbeddingClient:
    def __init__(self, settings: Settings):
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
        resp = await self.client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


def create_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.APP_ENV == "test":
        return FakeEmbeddingClient(dim=settings.EMBEDDING_DIM)
    if settings.EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddingClient(settings)
    raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")
```

(Set `EMBEDDING_MODEL=text-embedding-3-small` in `.env` — 1536 dims, matches the column. The startup dimension check from guide 01 catches any mismatch.)

## `backend/app/retrieval/vector_search.py`

Search is **global across all imported papers**, never project-filtered — discovering papers the user hasn't imported is the product. Project membership becomes a flag, not a filter.

⚠️ The asyncpg gotcha this file handles: a raw `text()` query bypasses SQLAlchemy's type machinery, and asyncpg doesn't know how to send a Python list as a `vector`. Passing the embedding as its string literal (`"[0.1,0.2,...]"`) and `CAST`-ing in SQL is the reliable fix. (ORM writes of `PaperChunk.embedding` are fine — the pgvector `Vector` column type stringifies on bind.)

```python
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def to_pgvector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


@dataclass(frozen=True)
class VectorHit:
    chunk_id: UUID
    paper_id: UUID
    text: str
    section: str | None
    title: str | None
    publication_year: int | None
    cited_by_count: int
    is_stub: bool
    similarity: float


_SEARCH_SQL = text(
    """
    SELECT pc.id, pc.paper_id, pc.text, pc.section,
           p.title, p.publication_year, p.cited_by_count, p.is_stub,
           1 - (pc.embedding <=> CAST(:query_embedding AS vector)) AS similarity
    FROM paper_chunks pc
    JOIN papers p ON p.id = pc.paper_id
    WHERE pc.embedding IS NOT NULL
    ORDER BY pc.embedding <=> CAST(:query_embedding AS vector)
    LIMIT :limit
    """
)


class VectorSearch:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(self, query_embedding: list[float], limit: int = 30) -> list[VectorHit]:
        result = await self.session.execute(
            _SEARCH_SQL,
            {"query_embedding": to_pgvector_literal(query_embedding), "limit": limit},
        )
        return [
            VectorHit(
                chunk_id=row.id,
                paper_id=row.paper_id,
                text=row.text,
                section=row.section,
                title=row.title,
                publication_year=row.publication_year,
                cited_by_count=row.cited_by_count or 0,
                is_stub=row.is_stub,
                similarity=float(row.similarity),
            )
            for row in result
        ]
```

(`<=>` is cosine *distance*; `1 - distance` = similarity. The `ORDER BY` expression matches the HNSW index operator class, so the index is actually used.)

## `backend/app/retrieval/graph_search.py`

Thin adapter over `graph.queries` — exists so `HybridRetriever` depends on one small object that tests can fake. Passes `GraphCandidate`s through untouched (their `features` feed the explanations).

```python
from neo4j import AsyncDriver

from app.graph import queries
from app.graph.queries import GraphCandidate


class GraphSearch:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def bibliographic_coupling(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        return await queries.bibliographic_coupling(self.driver, seeds, limit)

    async def co_citation(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        return await queries.co_citation(self.driver, seeds, limit)

    async def shared_concepts(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        return await queries.shared_concepts(self.driver, seeds, limit)

    async def direct_neighbors(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        return await queries.direct_neighbors(self.driver, seeds, limit)
```

## ⭐ `backend/app/retrieval/fusion.py`

Why RRF and not `0.5·similarity + 0.2·graph + ...`: the signals live on incompatible scales (cosine ∈ [0,1], citation counts unbounded, distances inverted), so hand-tuned weights are untestable guesswork. RRF uses only **ranks** — scale-free, one parameter (k=60, the literature default), and consensus-rewarding: rank 5 in three independent lists beats rank 1 in one. That property *is* the GraphRAG thesis in math form.

```python
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class FusedCandidate:
    paper_id: UUID
    score: float
    retrieval_sources: list[str]


def rrf_fuse(ranked_lists: dict[str, list[UUID]], k: int = 60) -> list[FusedCandidate]:
    """Reciprocal Rank Fusion: score(paper) = sum over lists of 1 / (k + rank).

    Ranks start at 1. Duplicates within one list count once, at their first
    (best) rank. Ties break on paper_id string for determinism.
    """
    scores: dict[UUID, float] = defaultdict(float)
    sources: dict[UUID, list[str]] = defaultdict(list)

    for source_name, papers in ranked_lists.items():
        seen: set[UUID] = set()
        rank = 0
        for paper_id in papers:
            if paper_id in seen:
                continue
            seen.add(paper_id)
            rank += 1
            scores[paper_id] += 1.0 / (k + rank)
            sources[paper_id].append(source_name)

    return sorted(
        (
            FusedCandidate(paper_id=paper_id, score=score, retrieval_sources=sources[paper_id])
            for paper_id, score in scores.items()
        ),
        key=lambda c: (-c.score, str(c.paper_id)),
    )
```

## `backend/app/retrieval/explain.py`

Reasons are rendered from **computed features, never LLM freeform** — so they can't be hallucinated, and you can debug retrieval by reading them.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalFeatures:
    retrieval_sources: list[str]
    shared_reference_count: int = 0
    co_citation_count: int = 0
    shared_concept_names: tuple[str, ...] = ()
    min_graph_distance: int | None = None
    cited_by_count: int = 0
    publication_year: int | None = None
    in_project: bool = False
    is_stub: bool = False


def render_reason(features: RetrievalFeatures) -> str:
    parts: list[str] = []
    sources = set(features.retrieval_sources)

    if "vector" in sources:
        parts.append("semantically close to your paragraph")
    if "coupling" in sources:
        if features.shared_reference_count:
            parts.append(f"shares {features.shared_reference_count} references with relevant papers")
        else:
            parts.append("shares references with relevant papers")
    if "co_citation" in sources:
        if features.co_citation_count:
            parts.append(f"co-cited with relevant papers by {features.co_citation_count} papers")
        else:
            parts.append("co-cited with relevant papers")
    if "shared_concepts" in sources:
        if features.shared_concept_names:
            concepts = ", ".join(features.shared_concept_names[:3])
            parts.append(f"shares concepts such as {concepts}")
        else:
            parts.append("shares concepts with relevant papers")
    if "citation_neighbors" in sources:
        parts.append("one citation hop from the papers matching your text")
    if features.in_project:
        parts.append("already in your project")
    if features.is_stub:
        parts.append("metadata is incomplete — import the full paper before citing")

    if not parts:
        return "Matched by the retrieval system, but no strong explanatory feature was available."
    reason = ", ".join(parts)
    return reason[0].upper() + reason[1:] + "."
```

(Uppercase only the first character — `str.capitalize()` would lowercase everything else and mangle concept names like "GraphRAG".)

## ⭐ `backend/app/retrieval/hybrid.py`

The pipeline: embed → vector top-30 → top-5 distinct papers become graph seeds → four graph lists → RRF → hydrate top-k with paper rows, project membership, best supporting chunk, and a rendered reason.

```python
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Paper, ProjectPaper
from app.graph.queries import GraphCandidate
from app.logging import get_logger
from app.retrieval.explain import RetrievalFeatures, render_reason
from app.retrieval.fusion import rrf_fuse
from app.retrieval.vector_search import VectorHit

log = get_logger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    paper_id: UUID
    title: str | None
    chunk_id: UUID | None
    text: str | None
    score: float
    retrieval_sources: list[str]
    reason: str
    in_project: bool
    is_stub: bool
    publication_year: int | None = None
    cited_by_count: int = 0


class HybridRetriever:
    """Depends on four small injected objects (embeddings, vector store, graph
    search, session) — which is exactly what makes it testable with fakes."""

    def __init__(self, embeddings, vector_store, graph, session: AsyncSession):
        self.embeddings = embeddings
        self.vector_store = vector_store
        self.graph = graph
        self.session = session

    async def retrieve(
        self,
        project_id: UUID,
        query: str,
        seed_paper_ids: list[UUID] | None = None,
        limit: int = 10,
    ) -> list[RetrievalResult]:
        # 1. Embed the query.
        query_embedding = (await self.embeddings.embed_texts([query]))[0]

        # 2. Vector list: top 30 chunks -> deduped ranked paper list,
        #    remembering each paper's best supporting chunk.
        hits = await self.vector_store.search(query_embedding, limit=30)
        vector_papers: list[UUID] = []
        best_hit: dict[UUID, VectorHit] = {}
        for hit in hits:
            if hit.paper_id not in best_hit:
                best_hit[hit.paper_id] = hit
                vector_papers.append(hit.paper_id)

        # 3. Seeds: explicit seeds, else top 5 distinct vector papers.
        seeds = seed_paper_ids or vector_papers[:5]
        seed_strs = [str(s) for s in seeds]

        # 4. One ranked list per graph signal.
        coupling: list[GraphCandidate] = []
        co_citation: list[GraphCandidate] = []
        shared_concepts: list[GraphCandidate] = []
        neighbors: list[GraphCandidate] = []
        if seed_strs:
            coupling = await self.graph.bibliographic_coupling(seed_strs, limit=20)
            co_citation = await self.graph.co_citation(seed_strs, limit=20)
            shared_concepts = await self.graph.shared_concepts(seed_strs, limit=20)
            neighbors = await self.graph.direct_neighbors(seed_strs, limit=20)

        # Collect per-paper features while converting candidates to id lists.
        features_by_paper: dict[UUID, dict] = {}

        def id_list(candidates: list[GraphCandidate]) -> list[UUID]:
            ids: list[UUID] = []
            for candidate in candidates:
                paper_id = UUID(candidate.paper_id)
                ids.append(paper_id)
                features_by_paper.setdefault(paper_id, {}).update(candidate.features)
            return ids

        # 5. Fuse with RRF.
        fused = rrf_fuse(
            {
                "vector": vector_papers,
                "coupling": id_list(coupling),
                "co_citation": id_list(co_citation),
                "shared_concepts": id_list(shared_concepts),
                "citation_neighbors": id_list(neighbors),
            },
            k=60,
        )

        log.info(
            "retrieval.hybrid",
            query_len=len(query),
            vector=len(vector_papers),
            coupling=len(coupling),
            co_citation=len(co_citation),
            shared_concepts=len(shared_concepts),
            neighbors=len(neighbors),
            fused=len(fused),
        )

        # 6. Hydrate the top candidates.
        return await self._hydrate(fused[:limit], project_id, best_hit, features_by_paper)

    async def _hydrate(
        self,
        candidates,
        project_id: UUID,
        best_hit: dict[UUID, VectorHit],
        features_by_paper: dict[UUID, dict],
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        ids = [c.paper_id for c in candidates]
        papers = {
            p.id: p
            for p in (
                await self.session.execute(select(Paper).where(Paper.id.in_(ids)))
            ).scalars()
        }
        in_project = {
            row[0]
            for row in (
                await self.session.execute(
                    select(ProjectPaper.paper_id).where(
                        ProjectPaper.project_id == project_id,
                        ProjectPaper.paper_id.in_(ids),
                    )
                )
            ).all()
        }

        results: list[RetrievalResult] = []
        for candidate in candidates:
            paper = papers.get(candidate.paper_id)
            if paper is None:
                continue
            hit = best_hit.get(candidate.paper_id)
            extra = features_by_paper.get(candidate.paper_id, {})
            features = RetrievalFeatures(
                retrieval_sources=candidate.retrieval_sources,
                shared_reference_count=extra.get("shared_reference_count", 0),
                co_citation_count=extra.get("co_citation_count", 0),
                shared_concept_names=tuple(extra.get("shared_concept_names", ())),
                min_graph_distance=extra.get("min_graph_distance"),
                cited_by_count=paper.cited_by_count or 0,
                publication_year=paper.publication_year,
                in_project=candidate.paper_id in in_project,
                is_stub=paper.is_stub,
            )
            results.append(
                RetrievalResult(
                    paper_id=candidate.paper_id,
                    title=paper.title,
                    chunk_id=hit.chunk_id if hit else None,
                    text=hit.text if hit else None,
                    score=candidate.score,
                    retrieval_sources=candidate.retrieval_sources,
                    reason=render_reason(features),
                    in_project=candidate.paper_id in in_project,
                    is_stub=paper.is_stub,
                    publication_year=paper.publication_year,
                    cited_by_count=paper.cited_by_count or 0,
                )
            )
        return results
```

Design points worth being able to defend:

- **Stubs stay in results**, flagged — a recommendation the user can act on by importing is a feature. The UI renders "Import full paper" instead of "Insert citation".
- **Features are for explanation, not scoring.** Scoring is pure RRF; the features hydrate the reason strings. When you someday have relevance labels, those same features become inputs to a learned ranker — RRF is the correct zero-data baseline.
- The embedding-dimension startup check lives in `db/postgres.py` (guide 01) — it's a schema concern, not a retrieval concern.

## Acceptance checks

```bash
docker compose exec backend pytest app/tests/test_fusion.py app/tests/test_hybrid_retrieval.py
```

Manual (after guides 05–08): import 3 related papers, confirm chunks have embeddings, call `retrieve_evidence`, and check that results include both vector-sourced and graph-only candidates, each with `retrieval_sources` and a readable reason mentioning graph signals.
