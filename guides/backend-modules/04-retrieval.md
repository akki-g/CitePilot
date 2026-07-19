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

**Comment style:** retrieval snippets include comments on the data flow. The central idea is to keep each signal separate until RRF fuses ranked paper IDs.

---

## `backend/app/retrieval/chunking.py`

One chunk per paper: `title + abstract`. Deliberately **no** synthetic concept/citation-summary chunks — template text clusters with other template text and pollutes top-k, and concept overlap is already a graph signal; encoding it in vector space would double-count it at fusion time.

```python
# dataclass is enough for a tiny immutable chunk value object.
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    # Always 0 for MVP because each paper has one chunk.
    chunk_index: int
    # Human-readable section name; later full-text parsing can add more sections.
    section: str
    # Text that will be embedded.
    text: str
    # Cheap metadata for future batching/debugging.
    token_count: int | None = None


def build_title_abstract_chunk(title: str | None, abstract: str | None) -> Chunk | None:
    # Strip empty values and keep title before abstract.
    parts = [part.strip() for part in [title, abstract] if part and part.strip()]
    if not parts:
        return None  # bare stub: nothing to embed yet
    # Separate title and abstract with a blank line so the embedding sees both clearly.
    text = "\n\n".join(parts)
    return Chunk(
        chunk_index=0,
        section="title_abstract",
        text=text,
        token_count=max(1, len(text.split())),  # word count as a cheap proxy
    )
```

Walkthrough:

- This function is pure and easy to test; ingestion can call it without DB/network dependencies.
- Returning `None` for bare stubs prevents embedding empty strings.
- One chunk keeps MVP retrieval simple and avoids double-counting graph concepts in vector space.

## `backend/app/retrieval/embeddings.py`

Provider-agnostic interface + one real provider + a deterministic fake. The fake is hash-seeded so vector tests are stable and never call an API.

```python
# Hashing powers deterministic fake embeddings.
import hashlib
# Random generates repeatable pseudo-vectors for tests.
import random
# Protocol defines the interface real/fake embedding clients must satisfy.
from typing import Protocol

# httpx calls the real embedding API.
import httpx

# Settings supplies provider/model/API-key/dimension.
from app.config import Settings


class EmbeddingClient(Protocol):
    # Interface used by HybridRetriever. Implementations can be fake or real.
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
```

Walkthrough:

- Retrieval code should only know about `EmbeddingClient`, not OpenAI specifics.
- `FakeEmbeddingClient` is essential for deterministic tests.
- The real provider is isolated behind one adapter, so swapping models later is contained.

(Set `EMBEDDING_MODEL=text-embedding-3-small` in `.env` — 1536 dims, matches the column. The startup dimension check from guide 01 catches any mismatch.)

## `backend/app/retrieval/vector_search.py`

Search is **global across all imported papers**, never project-filtered — discovering papers the user hasn't imported is the product. Project membership becomes a flag, not a filter.

⚠️ The asyncpg gotcha this file handles: a raw `text()` query bypasses SQLAlchemy's type machinery, and asyncpg doesn't know how to send a Python list as a `vector`. Passing the embedding as its string literal (`"[0.1,0.2,...]"`) and `CAST`-ing in SQL is the reliable fix. (ORM writes of `PaperChunk.embedding` are fine — the pgvector `Vector` column type stringifies on bind.)

```python
# dataclass gives an immutable row shape for search hits.
from dataclasses import dataclass
# UUID is the paper/chunk identity type from Postgres.
from uuid import UUID

# text() runs the hand-written pgvector SQL.
from sqlalchemy import text
# AsyncSession is the DB unit of work.
from sqlalchemy.ext.asyncio import AsyncSession


def to_pgvector_literal(embedding: list[float]) -> str:
    # asyncpg cannot bind Python lists as pgvector in raw text queries reliably.
    # Converting to "[...]" and CASTing in SQL makes the type explicit.
    return "[" + ",".join(str(x) for x in embedding) + "]"


@dataclass(frozen=True)
class VectorHit:
    # Chunk ID lets the UI/tool output cite the supporting text.
    chunk_id: UUID
    # Paper ID is what fusion/ranking operates on.
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
        # Store the DB session injected by route/tool/worker code.
        self.session = session

    async def search(self, query_embedding: list[float], limit: int = 30) -> list[VectorHit]:
        # Execute global vector search; do not filter to project papers.
        result = await self.session.execute(
            _SEARCH_SQL,
            {"query_embedding": to_pgvector_literal(query_embedding), "limit": limit},
        )
        # Convert SQLAlchemy rows into a stable typed shape.
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

SQL walkthrough:

- `pc.embedding <=> query_vector` is cosine distance under `vector_cosine_ops`.
- `1 - distance` is easier for humans to read as similarity.
- `ORDER BY pc.embedding <=> ...` matches the HNSW index operator and makes pgvector use the vector index.
- Joining `papers` hydrates title/year/stub metadata in the same query.

(`<=>` is cosine *distance*; `1 - distance` = similarity. The `ORDER BY` expression matches the HNSW index operator class, so the index is actually used.)

## `backend/app/retrieval/graph_search.py`

Thin adapter over `graph.queries` — exists so `HybridRetriever` depends on one small object that tests can fake. Passes `GraphCandidate`s through untouched (their `features` feed the explanations).

```python
# Neo4j driver type.
from neo4j import AsyncDriver

# graph.queries contains the actual Cypher; this adapter only delegates.
from app.graph import queries
# GraphCandidate is the common graph signal return type.
from app.graph.queries import GraphCandidate


class GraphSearch:
    def __init__(self, driver: AsyncDriver):
        # Keep just the driver so this object is easy to fake in tests.
        self.driver = driver

    async def bibliographic_coupling(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        # Papers sharing references with the seed papers.
        return await queries.bibliographic_coupling(self.driver, seeds, limit)

    async def co_citation(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        # Papers cited alongside the seed papers by third-party papers.
        return await queries.co_citation(self.driver, seeds, limit)

    async def shared_concepts(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        # Papers connected by concept nodes.
        return await queries.shared_concepts(self.driver, seeds, limit)

    async def direct_neighbors(self, seeds: list[str], limit: int = 20) -> list[GraphCandidate]:
        # One-hop citation neighbors.
        return await queries.direct_neighbors(self.driver, seeds, limit)
```

## ⭐ `backend/app/retrieval/fusion.py`

Why RRF and not `0.5·similarity + 0.2·graph + ...`: the signals live on incompatible scales (cosine ∈ [0,1], citation counts unbounded, distances inverted), so hand-tuned weights are untestable guesswork. RRF uses only **ranks** — scale-free, one parameter (k=60, the literature default), and consensus-rewarding: rank 5 in three independent lists beats rank 1 in one. That property *is* the GraphRAG thesis in math form.

```python
# defaultdict starts scores/sources automatically for unseen papers.
from collections import defaultdict
# dataclass for immutable fused candidates.
from dataclasses import dataclass
# UUID identifies papers across all ranked lists.
from uuid import UUID


@dataclass(frozen=True)
class FusedCandidate:
    # Paper being ranked.
    paper_id: UUID
    # RRF score. Absolute value is less important than ordering.
    score: float
    # Which signals contained this paper, e.g. ["vector", "co_citation"].
    retrieval_sources: list[str]


def rrf_fuse(ranked_lists: dict[str, list[UUID]], k: int = 60) -> list[FusedCandidate]:
    """Reciprocal Rank Fusion: score(paper) = sum over lists of 1 / (k + rank).

    Ranks start at 1. Duplicates within one list count once, at their first
    (best) rank. Ties break on paper_id string for determinism.
    """
    scores: dict[UUID, float] = defaultdict(float)
    sources: dict[UUID, list[str]] = defaultdict(list)

    # Iterate over each independent retrieval signal.
    for source_name, papers in ranked_lists.items():
        # A paper duplicated within one list should only count once.
        seen: set[UUID] = set()
        # Rank is counted after deduping.
        rank = 0
        for paper_id in papers:
            if paper_id in seen:
                continue
            seen.add(paper_id)
            rank += 1
            # RRF contribution: high ranks add slightly more than low ranks.
            scores[paper_id] += 1.0 / (k + rank)
            # Remember which signal supported this candidate for explanations.
            sources[paper_id].append(source_name)

    # Convert score dictionaries into sorted FusedCandidate objects.
    return sorted(
        (
            FusedCandidate(paper_id=paper_id, score=score, retrieval_sources=sources[paper_id])
            for paper_id, score in scores.items()
        ),
        key=lambda c: (-c.score, str(c.paper_id)),
    )
```

Fusion walkthrough:

- Inputs are paper ID lists, not raw similarity/count scores.
- RRF deliberately ignores scale differences across vector similarity and graph counts.
- `k=60` dampens rank differences so cross-signal consensus matters.
- Deterministic tie-breaking makes tests stable.

## `backend/app/retrieval/explain.py`

Reasons are rendered from **computed features, never LLM freeform** — so they can't be hallucinated, and you can debug retrieval by reading them.

```python
# dataclass for explanation feature bundle.
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalFeatures:
    # Signal names from RRF.
    retrieval_sources: list[str]
    # Optional graph feature values used only for the reason text.
    shared_reference_count: int = 0
    co_citation_count: int = 0
    shared_concept_names: tuple[str, ...] = ()
    min_graph_distance: int | None = None
    cited_by_count: int = 0
    publication_year: int | None = None
    in_project: bool = False
    is_stub: bool = False


def render_reason(features: RetrievalFeatures) -> str:
    # Accumulate short evidence-backed phrases.
    parts: list[str] = []
    # Set membership makes "did this source contribute?" checks simple.
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
        # Fallback should be honest when no explainable feature is present.
        return "Matched by the retrieval system, but no strong explanatory feature was available."
    reason = ", ".join(parts)
    return reason[0].upper() + reason[1:] + "."
```

Explanation walkthrough:

- Reasons are deterministic strings based on computed features.
- The LLM can use these reasons, but it is not allowed to invent them.
- Stub warning is part of the reason because stubs should be imported before citation insertion.

(Uppercase only the first character — `str.capitalize()` would lowercase everything else and mangle concept names like "GraphRAG".)

## ⭐ `backend/app/retrieval/hybrid.py`

The pipeline: embed → vector top-30 → top-5 distinct papers become graph seeds → four graph lists → RRF → hydrate top-k with paper rows, project membership, best supporting chunk, and a rendered reason.

```python
# Future annotations keep type hints flexible.
from __future__ import annotations

# dataclass for result objects.
from dataclasses import dataclass
# UUID is the paper/project identity type.
from uuid import UUID

# select hydrates papers/project membership from Postgres.
from sqlalchemy import select
# AsyncSession is the DB unit of work.
from sqlalchemy.ext.asyncio import AsyncSession

# ORM rows for paper metadata and project membership.
from app.db.models import Paper, ProjectPaper
# GraphCandidate carries per-signal graph features.
from app.graph.queries import GraphCandidate
# Structured retrieval logs.
from app.logging import get_logger
# Explanation rendering.
from app.retrieval.explain import RetrievalFeatures, render_reason
# RRF fusion.
from app.retrieval.fusion import rrf_fuse
# Best vector hits provide supporting snippets.
from app.retrieval.vector_search import VectorHit

# Module logger.
log = get_logger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    # Final API/tool shape for one recommended paper.
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
        # Dependency injection makes this class testable with fake components.
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
        # Collect final paper IDs to hydrate in two SQL queries.
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
            # Skip candidates that no longer exist in Postgres.
            paper = papers.get(candidate.paper_id)
            if paper is None:
                continue
            hit = best_hit.get(candidate.paper_id)
            # Merge graph features collected before fusion.
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

Hybrid walkthrough:

- Query embedding happens once per user request.
- Vector search produces chunk hits, but fusion ranks papers, so vector hits are deduped by paper.
- Top vector papers become graph seeds when the user does not provide explicit seeds.
- Each graph signal produces an independent ranked list.
- `features_by_paper` keeps explanation details while RRF remains rank-only.
- `_hydrate()` turns paper IDs back into user-facing metadata/snippets/reasons.

Design points worth being able to defend:

- **Stubs stay in results**, flagged — a recommendation the user can act on by importing is a feature. The UI renders "Import full paper" instead of "Insert citation".
- **Features are for explanation, not scoring.** Scoring is pure RRF; the features hydrate the reason strings. When you someday have relevance labels, those same features become inputs to a learned ranker — RRF is the correct zero-data baseline.
- The embedding-dimension startup check lives in `db/postgres.py` (guide 01) — it's a schema concern, not a retrieval concern.

## Acceptance checks

```bash
docker compose exec backend pytest app/tests/test_fusion.py app/tests/test_hybrid_retrieval.py
```

Manual (after guides 05–08): import 3 related papers, confirm chunks have embeddings, call `retrieve_evidence`, and check that results include both vector-sourced and graph-only candidates, each with `retrieval_sources` and a readable reason mentioning graph signals.

---

## Changes (review pass, 2026-07-05)

The following issues were found in the implemented files and fixed directly (each fix site is marked with a `# fix:` comment in the code):

1. **`backend/app/retrieval/embeddings.py` — the `EmbeddingClient` Protocol declared `embed_text`, not `embed_texts`.** Both implementations (`FakeEmbeddingClient`, `OpenAIEmbeddingClient`) and both callers (`hybrid.py`, `workers/jobs.py`) use `embed_texts`. Protocols are structural, so this wouldn't crash at runtime, but the declared interface contract was wrong and any type checker would flag every implementation as non-conforming. Renamed to `embed_texts`.

2. **`backend/app/retrieval/hybrid.py` — three bugs:**
   - `vector_papers: list[UUID]` was a bare annotation with no assignment. The first `vector_papers.append(...)` would raise `UnboundLocalError`, killing every retrieval call that had at least one vector hit. Initialized to `[]`.
   - The `RetrievalResult` dataclass field was named `chunk`, but `_hydrate` constructs `RetrievalResult(chunk_id=...)` — a guaranteed `TypeError` the first time any result was hydrated. Renamed the field to `chunk_id` per this guide (guide 09's tests also construct results with `chunk_id=`).
   - `retrieve()` ended with `return self._hydrate(...)` without `await`, returning a coroutine object instead of `list[RetrievalResult]`. Callers iterating the "list" would fail (and the coroutine would leak un-awaited). Added the `await`.

No changes were needed to `chunking.py`, `vector_search.py`, `graph_search.py`, `fusion.py`, or `explain.py` — they match this guide. (One harmless naming divergence left as-is: `vector_search.py` names its helper `to_pg_vector_literal` instead of the guide's `to_pgvector_literal`; it is defined and used consistently within the file and nothing else imports it.)
