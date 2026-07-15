# postgres -> neo4j mirroring
# idempotent by construction: MERGER on the pg uuid, the SET current properties, reimports and resyncs are free

from __future__ import annotations
from collections.abc import Sequence
from uuid import UUID

from neo4j import AsyncDriver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Author, Citation, Concept, Paper, PaperAuthor, PaperConcept
from app.logging import get_logger

log = get_logger(__name__)


async def sync_paper(session: AsyncSession, driver: AsyncDriver, paper_id: UUID) -> None:
    """Mirror one paper + its author/venue/concepts into neo4j"""

    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise ValueError(f"Paper not found: {paper_id}")
    
    authors = (
        await session.execute(
            select(Author, PaperAuthor.author_order)
            .join(PaperAuthor, PaperAuthor.author_id == Author.id)
            # fix: compared against the Paper ORM object (`== paper`) instead of the UUID
            .where(PaperAuthor.paper_id == paper_id)
        )
    ).all()

    concepts = (
        await session.execute(
            select(Concept, PaperConcept.score, PaperConcept.source)
            .join(PaperConcept, PaperConcept.concept_id == Concept.id)
            .where(PaperConcept.paper_id == paper_id)
        )
    ).all()

    author_payload = [
        {
            "id": str(author.id),
            "openalex_id": author.openalex_id,
            "name": author.name,
            "author_order": author_order,
        }
        for author, author_order in authors
    ]
    concept_payload = [
        {
            "id": str(concept.id),
            "name": concept.name,
            "score": score,
            "source": source,
        }
        for concept, score, source in concepts
    ]

    # Mirror a paper and all of its small relationship collections in one
    # Bolt round trip. Imports used to issue one query per author and concept,
    # which made graph sync grow linearly with metadata richness.
    async with driver.session() as graph:
        await graph.run(
            """
            MERGE (p:Paper {id: $id})
            SET p.openalex_id = $openalex_id,
                p.doi = $doi,
                p.title = $title,
                p.year = $year,
                p.cited_by_count = $cited_by_count,
                p.is_stub = $is_stub
            FOREACH (row IN $authors |
                MERGE (a:Author {id: row.id})
                SET a.openalex_id = row.openalex_id,
                    a.name = row.name
                MERGE (p)-[r:WRITTEN_BY]->(a)
                SET r.author_order = row.author_order
            )
            FOREACH (venue IN CASE WHEN $venue_name IS NULL THEN [] ELSE [$venue_name] END |
                MERGE (v:Venue {name: venue})
                MERGE (p)-[:PUBLISHED_IN]->(v)
            )
            FOREACH (row IN $concepts |
                MERGE (c:Concept {name: row.name})
                SET c.id = row.id
                MERGE (p)-[r:MENTIONS_CONCEPT]->(c)
                SET r.score = row.score,
                    r.source = row.source
            )
            """,
            id=str(paper.id),
            openalex_id=paper.openalex_id,
            doi=paper.doi,
            title=paper.title,
            year=paper.publication_year,
            # fix: cited_by_count kwarg was missing but the query references $cited_by_count
            cited_by_count=paper.cited_by_count,
            is_stub=paper.is_stub,
            authors=author_payload,
            venue_name=paper.venue_name,
            concepts=concept_payload,
        )

    log.info("graph.sync.paper_completed", paper_id=str(paper_id))


async def sync_stub_papers(driver: AsyncDriver, papers: Sequence[Paper]) -> None:
    """Batch-MERGE minimal Paper nodes in one round trip.

    Called on ingest for a paper's references, so CITES edges have endpoints to
    attach to. Without this, sync_citations MATCHes nothing and the graph stays
    empty — the single most common way this feature silently breaks.
    """
    if not papers:
        return
    payload = [
        {
            "id": str(p.id),
            "openalex_id": p.openalex_id,
            "title": p.title,
            "year": p.publication_year,
            "cited_by_count": p.cited_by_count or 0,
            "is_stub": p.is_stub,
        }
        for p in papers
    ]
    async with driver.session() as graph:
        await graph.run(
            """
            UNWIND $papers AS row
            MERGE (p:Paper {id: row.id})
            SET p.openalex_id = row.openalex_id,
                p.title = row.title,
                p.year = row.year,
                p.cited_by_count = row.cited_by_count,
                p.is_stub = row.is_stub
            """,
            papers=payload,
        )
    log.info("graph.sync.stubs_completed", count=len(payload))


async def sync_citations(driver: AsyncDriver, citing_id: UUID, cited_ids: Sequence[UUID]) -> None:
    """Batch-MERGE CITES edges in one round trip."""
    if not cited_ids:
        return
    async with driver.session() as graph:
        await graph.run(
            """
            MATCH (citing:Paper {id: $citing_id})
            UNWIND $cited_ids AS cited_id
            MATCH (cited:Paper {id: cited_id})
            MERGE (citing)-[:CITES]->(cited)
            """,
            citing_id=str(citing_id),
            cited_ids=[str(pid) for pid in cited_ids],
        )
    log.info("graph.sync.citations_completed", citing_id=str(citing_id), count=len(cited_ids))


async def resync_graph(session: AsyncSession, driver: AsyncDriver) -> None:
    """Wipe Neo4j and rebuild it from Postgres — the proof that Neo4j is derived."""
    log.info("graph.resync.started")
    async with driver.session() as graph:
        await graph.run("MATCH (n) DETACH DELETE n")

    paper_ids = [row[0] for row in (await session.execute(select(Paper.id))).all()]
    for paper_id in paper_ids:
        await sync_paper(session, driver, paper_id)

    citation_rows = (
        await session.execute(select(Citation.citing_paper_id, Citation.cited_paper_id))
    ).all()
    by_citing: dict[UUID, list[UUID]] = {}
    for citing_id, cited_id in citation_rows:
        by_citing.setdefault(citing_id, []).append(cited_id)

    for citing_id, cited_ids in by_citing.items():
        await sync_citations(driver, citing_id, cited_ids)

    log.info("graph.resync.completed", papers=len(paper_ids), citations=len(citation_rows))
