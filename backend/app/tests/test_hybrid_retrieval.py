import asyncio
from uuid import uuid4

from app.db.models import Paper
from app.graph.queries import GraphCandidate
from app.retrieval.embeddings import FakeEmbeddingClient
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_search import VectorHit


class FakeVectorStore:
    def __init__(self, hits: list[VectorHit]):
        self.hits = hits

    async def search(self, query_embedding, limit=30):
        return self.hits


class FakeGraphSearch:
    def __init__(self, co_citation: list[GraphCandidate]):
        self._co_citation = co_citation

    async def bibliographic_coupling(self, seeds, limit=20):
        return []

    async def co_citation(self, seeds, limit=20):
        return self._co_citation

    async def shared_concepts(self, seeds, limit=20):
        return []

    async def direct_neighbors(self, seeds, limit=20):
        return []


class ConcurrentGraphSearch:
    """Blocks each signal until all four have started."""

    def __init__(self):
        self.started = 0
        self.all_started = asyncio.Event()

    async def _signal(self):
        self.started += 1
        if self.started == 4:
            self.all_started.set()
        await self.all_started.wait()
        return []

    async def bibliographic_coupling(self, seeds, limit=20):
        return await self._signal()

    async def co_citation(self, seeds, limit=20):
        return await self._signal()

    async def shared_concepts(self, seeds, limit=20):
        return await self._signal()

    async def direct_neighbors(self, seeds, limit=20):
        return await self._signal()


async def test_graph_signals_start_concurrently():
    graph = ConcurrentGraphSearch()
    retriever = HybridRetriever(
        embeddings=FakeEmbeddingClient(dim=8),
        vector_store=FakeVectorStore([]),
        graph=graph,
        session=None,
    )

    results = await asyncio.wait_for(
        retriever.retrieve(
            project_id=uuid4(),
            query="graph retrieval",
            seed_paper_ids=[uuid4()],
        ),
        timeout=1,
    )

    assert results == []
    assert graph.started == 4


async def test_hybrid_includes_vector_and_graph_candidates(db_session):
    vector_paper = Paper(title="Vector Paper", is_stub=False, cited_by_count=10)
    graph_paper = Paper(title="Graph Paper", is_stub=False, cited_by_count=99)
    db_session.add_all([vector_paper, graph_paper])
    await db_session.commit()

    hit = VectorHit(
        chunk_id=uuid4(),
        paper_id=vector_paper.id,
        text="supporting chunk text",
        section="title_abstract",
        title="Vector Paper",
        publication_year=2024,
        cited_by_count=10,
        is_stub=False,
        similarity=0.93,
    )
    retriever = HybridRetriever(
        embeddings=FakeEmbeddingClient(dim=8),
        vector_store=FakeVectorStore([hit]),
        graph=FakeGraphSearch(
            [
                GraphCandidate(
                    paper_id=str(graph_paper.id),
                    score=7.0,
                    signal="co_citation",
                    features={"co_citation_count": 7},
                )
            ]
        ),
        session=db_session,
    )

    results = await retriever.retrieve(project_id=uuid4(), query="graph retrieval", limit=10)
    by_id = {r.paper_id: r for r in results}

    assert vector_paper.id in by_id, "vector-only candidate must appear"
    assert graph_paper.id in by_id, "graph-only candidate must appear"
    assert by_id[vector_paper.id].retrieval_sources == ["vector"]
    assert by_id[graph_paper.id].retrieval_sources == ["co_citation"]
    assert by_id[vector_paper.id].text == "supporting chunk text"
    # case-insensitive: render_reason uppercases the first character, so a graph-only
    # candidate's reason starts with "Co-cited ..."
    assert "co-cited" in by_id[graph_paper.id].reason.lower()
    assert all(r.reason for r in results)
