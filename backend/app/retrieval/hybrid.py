from __future__ import annotations

import asyncio
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

# final API/tool shape for one recommended paper
@dataclass(frozen=True)
class RetrievalResult:
    paper_id: UUID
    title: str | None
    # fix: field was named `chunk` but _hydrate constructs RetrievalResult(chunk_id=...)
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
    """
    Depends on 4 small injected objects (embeddings, vector store, graph search, session) 
    this makes it testable with fakes
    """

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
        # embed the query
        query_embedding = (await self.embeddings.embed_texts([query]))[0]

        # vector list: top 30 chunks -> deduped ranked paper ist
        # remembering each paper's best supporting chunk
        hits = await self.vector_store.search(query_embedding, limit=30)
        # fix: was a bare annotation `vector_papers: list[UUID]` with no value — UnboundLocalError on append
        vector_papers: list[UUID] = []
        best_hit: dict[UUID, VectorHit] = {}
        for hit in hits:
            if hit.paper_id not in best_hit:
                best_hit[hit.paper_id] = hit
                vector_papers.append(hit.paper_id)

        
        # seeds: explicit seeds, else top 5 distinct vector papers
        seeds = seed_paper_ids or vector_papers[:5]
        seed_strs = [str(s) for s in seeds] 

        # 1 ranked list per graph signal
        coupling: list[GraphCandidate] = []
        co_citation: list[GraphCandidate] = []
        shared_concepts: list[GraphCandidate] = []
        neighbors: list[GraphCandidate] = []

        if seed_strs:
            # These signals are independent ranked lists. Running them together
            # changes no ranking semantics and reduces graph latency from the
            # sum of four Neo4j round trips to roughly the slowest one.
            coupling, co_citation, shared_concepts, neighbors = await asyncio.gather(
                self.graph.bibliographic_coupling(seed_strs, limit=20),
                self.graph.co_citation(seed_strs, limit=20),
                self.graph.shared_concepts(seed_strs, limit=20),
                self.graph.direct_neighbors(seed_strs, limit=20),
            )


        features_by_paper: dict[UUID, dict] = {}

        def id_list(candidates: list[GraphCandidate]) -> list[UUID]:
            ids: list[UUID] = []
            for candidate in candidates:
                paper_id = UUID(candidate.paper_id)
                ids.append(paper_id)
                features_by_paper.setdefault(paper_id, {}).update(candidate.features)

            return ids
        
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

        # fix: was missing `await` — returned a coroutine object instead of the result list
        return await self._hydrate(fused[:limit], project_id, best_hit, features_by_paper)


    async def _hydrate(
            self, 
            candidates,
            project_id:UUID,
            best_hit: dict[UUID, VectorHit],
            features_by_paper: dict[UUID, dict],
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        
        # collect final paper IDs to hydrate in 2 sql queries
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
            # skip papers that are no longer in pg
            paper = papers.get(candidate.paper_id)
            if paper is None:
                continue

            hit = best_hit.get(candidate.paper_id)

            # merge graph feats collected before fusion
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
    
# query embeddings happens once per user request
# vector search produces chunk hits, but fusion ranks papers, so vector hits are deduped by paper,
# top vector papers become graph seeds when the user does not provide explicit seeds
# each graph signal produced an independent ranked list
# features by paper keeps explanation details while RRF remains rank-only
# _hydrate() turns paper IDs back into user-facing metadata/snippets/reasons
