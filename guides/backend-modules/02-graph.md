# Module Guide: Graph

Files in this guide (all complete — type them as-is):

- `backend/app/graph/neo4j_client.py`
- `backend/app/graph/schema.py`
- `backend/app/graph/queries.py` ⭐ core learning file
- `backend/app/graph/sync.py` ⭐ core learning file
- `backend/app/graph/resync.py`
- `infra/scripts/init_neo4j.cypher`

**Why this module:** Neo4j is a rebuildable mirror of Postgres that exists for one reason — relationship traversal (references/citers, bibliographic coupling, co-citation, shared concepts, graph-panel neighborhoods). `resync.py` proves it's derived: wipe Neo4j, rebuild from Postgres in one command.

⭐ files are the interview material — type them slowly and be able to draw the coupling and co-citation patterns on a whiteboard.

---

## `backend/app/graph/neo4j_client.py`

One driver per process; the driver owns the connection pool, sessions are borrowed per unit of work.

```python
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import Settings


def create_neo4j_driver(settings: Settings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
```

## `backend/app/graph/schema.py`

Applied idempotently at every startup. Uniqueness constraints double as indexes — without them, every `MERGE (p:Paper {id: ...})` is a full graph scan.

```python
from neo4j import AsyncDriver

CONSTRAINT_STATEMENTS = [
    "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE",
    "CREATE CONSTRAINT author_id_unique IF NOT EXISTS "
    "FOR (a:Author) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT concept_name_unique IF NOT EXISTS "
    "FOR (c:Concept) REQUIRE c.name IS UNIQUE",
    "CREATE INDEX paper_year_index IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    "CREATE INDEX paper_stub_index IF NOT EXISTS FOR (p:Paper) ON (p.is_stub)",
]


async def apply_constraints(driver: AsyncDriver) -> None:
    async with driver.session() as session:
        for statement in CONSTRAINT_STATEMENTS:
            await session.run(statement)
```

## `infra/scripts/init_neo4j.cypher`

Same statements with `;` terminators, for pasting into the Neo4j browser manually.

```cypher
CREATE CONSTRAINT paper_id_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT paper_openalex_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.openalex_id IS UNIQUE;

CREATE CONSTRAINT author_id_unique IF NOT EXISTS
FOR (a:Author) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT concept_name_unique IF NOT EXISTS
FOR (c:Concept) REQUIRE c.name IS UNIQUE;

CREATE INDEX paper_year_index IF NOT EXISTS FOR (p:Paper) ON (p.year);

CREATE INDEX paper_stub_index IF NOT EXISTS FOR (p:Paper) ON (p.is_stub);
```

## ⭐ `backend/app/graph/queries.py`

All Cypher lives here, parameterized. Every traversal has a budget: **never** use the undirected variable-length pattern `-[:CITES*1..2]-` with a bare LIMIT — around a hub node (a survey cited 10k times) it explodes, and LIMIT truncates arbitrarily. Expand per direction with a per-hop cap, ordered by a quality signal before limiting.

The two bibliometrics to internalize:

- **Bibliographic coupling** `(seed)-[:CITES]->(ref)<-[:CITES]-(other)` — other papers that build on the same foundations (finds contemporaries/competitors).
- **Co-citation** `(citing)-[:CITES]->(seed)`, `(citing)-[:CITES]->(other)` — papers the community treats as companions of the seed.

```python
from dataclasses import dataclass, field

from neo4j import AsyncDriver


@dataclass(frozen=True)
class GraphCandidate:
    """One paper produced by one graph signal, with the features that explain it."""

    paper_id: str
    score: float
    signal: str
    features: dict = field(default_factory=dict)


_DIRECT_NEIGHBORS = """
UNWIND $paper_ids AS seed_id
MATCH (seed:Paper {id: seed_id})-[:CITES]-(other:Paper)
WHERE NOT other.id IN $paper_ids
RETURN other.id AS paper_id,
       count(DISTINCT seed_id) AS seed_links,
       max(other.cited_by_count) AS cited_by_count
ORDER BY seed_links DESC, cited_by_count DESC
LIMIT $limit
"""

_BIBLIOGRAPHIC_COUPLING = """
UNWIND $paper_ids AS seed_id
MATCH (seed:Paper {id: seed_id})-[:CITES]->(ref:Paper)<-[:CITES]-(other:Paper)
WHERE NOT other.id IN $paper_ids
RETURN other.id AS paper_id,
       count(DISTINCT ref) AS shared_references,
       max(other.cited_by_count) AS cited_by_count
ORDER BY shared_references DESC, cited_by_count DESC
LIMIT $limit
"""

_CO_CITATION = """
UNWIND $paper_ids AS seed_id
MATCH (citing:Paper)-[:CITES]->(seed:Paper {id: seed_id})
MATCH (citing)-[:CITES]->(other:Paper)
WHERE NOT other.id IN $paper_ids
RETURN other.id AS paper_id,
       count(DISTINCT citing) AS co_citation_count,
       max(other.cited_by_count) AS cited_by_count
ORDER BY co_citation_count DESC, cited_by_count DESC
LIMIT $limit
"""

_SHARED_CONCEPTS = """
UNWIND $paper_ids AS seed_id
MATCH (seed:Paper {id: seed_id})-[:MENTIONS_CONCEPT]->(c:Concept)<-[:MENTIONS_CONCEPT]-(other:Paper)
WHERE NOT other.id IN $paper_ids
RETURN other.id AS paper_id,
       collect(DISTINCT c.name) AS shared_concepts,
       count(DISTINCT c) AS concept_overlap,
       max(other.cited_by_count) AS cited_by_count
ORDER BY concept_overlap DESC, cited_by_count DESC
LIMIT $limit
"""

_REFERENCES_OF = """
MATCH (seed:Paper {id: $paper_id})-[:CITES]->(cited:Paper)
RETURN cited.id AS paper_id, cited.cited_by_count AS cited_by_count
ORDER BY cited.cited_by_count DESC
LIMIT $limit
"""

_CITERS_OF = """
MATCH (citing:Paper)-[:CITES]->(seed:Paper {id: $paper_id})
RETURN citing.id AS paper_id, citing.cited_by_count AS cited_by_count
ORDER BY citing.cited_by_count DESC
LIMIT $limit
"""

# Two-hop neighborhood for the graph panel, capped per direction. The CASE/UNWIND
# trick keeps the row alive when a paper has no neighbors at all.
_TWO_HOP_NEIGHBORHOOD = """
MATCH (seed:Paper {id: $paper_id})
CALL {
  WITH seed
  MATCH (seed)-[:CITES]->(n1:Paper)
  RETURN n1 ORDER BY n1.cited_by_count DESC LIMIT $per_hop
  UNION
  WITH seed
  MATCH (n1:Paper)-[:CITES]->(seed)
  RETURN n1 ORDER BY n1.cited_by_count DESC LIMIT $per_hop
}
WITH seed, collect(DISTINCT n1) AS hop1s
UNWIND (CASE WHEN size(hop1s) = 0 THEN [null] ELSE hop1s END) AS h
OPTIONAL MATCH (h)-[r:CITES]-(m:Paper)
WHERE m = seed OR m IN hop1s
WITH seed, hop1s,
     [rel IN collect(DISTINCT r) WHERE rel IS NOT NULL |
       {source: startNode(rel).id, target: endNode(rel).id}] AS edges
RETURN seed, hop1s, edges
"""


async def direct_neighbors(
    driver: AsyncDriver, paper_ids: list[str], limit: int = 20
) -> list[GraphCandidate]:
    """One undirected hop from the seeds. Single-hop undirected is safe; only
    variable-length undirected expansion is the trap."""
    if not paper_ids:
        return []
    records, _, _ = await driver.execute_query(_DIRECT_NEIGHBORS, paper_ids=paper_ids, limit=limit)
    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["seed_links"]),
            signal="citation_neighbors",
            features={"seed_links": r["seed_links"], "min_graph_distance": 1},
        )
        for r in records
    ]


async def bibliographic_coupling(
    driver: AsyncDriver, paper_ids: list[str], limit: int = 20
) -> list[GraphCandidate]:
    if not paper_ids:
        return []
    records, _, _ = await driver.execute_query(
        _BIBLIOGRAPHIC_COUPLING, paper_ids=paper_ids, limit=limit
    )
    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["shared_references"]),
            signal="coupling",
            features={"shared_reference_count": r["shared_references"]},
        )
        for r in records
    ]


async def co_citation(
    driver: AsyncDriver, paper_ids: list[str], limit: int = 20
) -> list[GraphCandidate]:
    if not paper_ids:
        return []
    records, _, _ = await driver.execute_query(_CO_CITATION, paper_ids=paper_ids, limit=limit)
    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["co_citation_count"]),
            signal="co_citation",
            features={"co_citation_count": r["co_citation_count"]},
        )
        for r in records
    ]


async def shared_concepts(
    driver: AsyncDriver, paper_ids: list[str], limit: int = 20
) -> list[GraphCandidate]:
    if not paper_ids:
        return []
    records, _, _ = await driver.execute_query(_SHARED_CONCEPTS, paper_ids=paper_ids, limit=limit)
    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["concept_overlap"]),
            signal="shared_concepts",
            features={
                "concept_overlap": r["concept_overlap"],
                "shared_concept_names": list(r["shared_concepts"])[:5],
            },
        )
        for r in records
    ]


async def references_of(
    driver: AsyncDriver, paper_id: str, limit: int = 20
) -> list[GraphCandidate]:
    records, _, _ = await driver.execute_query(_REFERENCES_OF, paper_id=paper_id, limit=limit)
    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["cited_by_count"] or 0),
            signal="reference",
            features={"direction": "seed_cites_it"},
        )
        for r in records
    ]


async def citers_of(driver: AsyncDriver, paper_id: str, limit: int = 20) -> list[GraphCandidate]:
    records, _, _ = await driver.execute_query(_CITERS_OF, paper_id=paper_id, limit=limit)
    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["cited_by_count"] or 0),
            signal="citer",
            features={"direction": "it_cites_seed"},
        )
        for r in records
    ]


def _node_dict(node, is_seed: bool = False) -> dict:
    return {
        "id": node["id"],
        "title": node.get("title"),
        "year": node.get("year"),
        "cited_by_count": node.get("cited_by_count") or 0,
        "is_stub": bool(node.get("is_stub")),
        "is_seed": is_seed,
    }


async def two_hop_neighborhood(driver: AsyncDriver, paper_id: str, per_hop: int = 15) -> dict:
    """Nodes + edges for the graph panel: seed, capped hop-1 papers in both
    directions, and every CITES edge among that node set."""
    records, _, _ = await driver.execute_query(
        _TWO_HOP_NEIGHBORHOOD, paper_id=paper_id, per_hop=per_hop
    )
    if not records:
        return {"nodes": [], "edges": []}
    record = records[0]
    nodes = [_node_dict(record["seed"], is_seed=True)]
    nodes += [_node_dict(n) for n in record["hop1s"]]

    seen: set[tuple[str, str]] = set()
    edges: list[dict] = []
    for edge in record["edges"]:
        key = (edge["source"], edge["target"])
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": edge["source"], "target": edge["target"], "type": "CITES"})
    return {"nodes": nodes, "edges": edges}
```

Notes:

- `driver.execute_query` returns `(records, summary, keys)` — the modern one-shot API; use it for reads. `session.run` in `sync.py` is the unit-of-work API for writes.
- Every function takes/returns **string UUIDs** — Neo4j properties are strings; callers convert at the boundary.
- `UNWIND $paper_ids` batches multi-seed queries into one round trip instead of one query per seed.

## ⭐ `backend/app/graph/sync.py`

Postgres → Neo4j mirroring. Idempotent by construction: `MERGE` on the Postgres UUID, then `SET` current properties — re-imports and re-syncs are free.

```python
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
    """Mirror one paper + its authors/venue/concepts into Neo4j."""
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise ValueError(f"Paper not found: {paper_id}")

    authors = (
        await session.execute(
            select(Author, PaperAuthor.author_order)
            .join(PaperAuthor, PaperAuthor.author_id == Author.id)
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
            """,
            id=str(paper.id),
            openalex_id=paper.openalex_id,
            doi=paper.doi,
            title=paper.title,
            year=paper.publication_year,
            cited_by_count=paper.cited_by_count,
            is_stub=paper.is_stub,
        )

        for author, author_order in authors:
            await graph.run(
                """
                MATCH (p:Paper {id: $paper_id})
                MERGE (a:Author {id: $author_id})
                SET a.openalex_id = $openalex_id,
                    a.name = $name
                MERGE (p)-[r:WRITTEN_BY]->(a)
                SET r.author_order = $author_order
                """,
                paper_id=str(paper.id),
                author_id=str(author.id),
                openalex_id=author.openalex_id,
                name=author.name,
                author_order=author_order,
            )

        if paper.venue_name:
            await graph.run(
                """
                MATCH (p:Paper {id: $paper_id})
                MERGE (v:Venue {name: $venue_name})
                MERGE (p)-[:PUBLISHED_IN]->(v)
                """,
                paper_id=str(paper.id),
                venue_name=paper.venue_name,
            )

        for concept, score, source in concepts:
            await graph.run(
                """
                MATCH (p:Paper {id: $paper_id})
                MERGE (c:Concept {name: $name})
                SET c.id = $concept_id
                MERGE (p)-[r:MENTIONS_CONCEPT]->(c)
                SET r.score = $score,
                    r.source = $source
                """,
                paper_id=str(paper.id),
                concept_id=str(concept.id),
                name=concept.name,
                score=score,
                source=source,
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
```

(Per-author/per-concept round trips are fine at POC scale; batching them with `UNWIND` like `sync_stub_papers` is the obvious optimization to mention in an interview.)

## `backend/app/graph/resync.py`

Standalone entrypoint for `make resync-graph` (`python -m app.graph.resync`).

```python
import asyncio

from app.config import get_settings
from app.db.postgres import create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver
from app.graph.schema import apply_constraints
from app.graph.sync import resync_graph


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    driver = create_neo4j_driver(settings)
    try:
        await apply_constraints(driver)
        async with session_factory() as session:
            await resync_graph(session, driver)
    finally:
        await driver.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

## Acceptance checks

After guide 03's ingestion works, import one paper, then:

```bash
docker compose exec backend python -m app.graph.resync
```

In the Neo4j browser:

```cypher
MATCH (p:Paper) RETURN count(p);
MATCH (:Paper)-[r:CITES]->(:Paper) RETURN count(r);
MATCH (p:Paper {is_stub: true}) RETURN count(p);
```

Expected: the imported paper + its reference stubs exist as `Paper` nodes, `CITES` edges exist, stub count matches the paper's reference count, and wiping Neo4j (`MATCH (n) DETACH DELETE n`) followed by `make resync-graph` restores identical counts.
