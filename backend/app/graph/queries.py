# all cypher lives here, parameterized
# every traversal has a budget: never use the undirected variable-length pattern -[CITES*1..2]- with a bare limit
# expand per difection with a per-hop cap, ordered by a quality signal before limiting

# the 2 bibliometrics
# biblographic coupling (seed)-[:CITES]->(ref)<-[:CITES]-(other): other papers that build on the same foundations 
# co-citation (citing)-[:CITES]->(seed) : papers the community treates as companions of the seed

from dataclasses import dataclass, field

from neo4j import AsyncDriver


@dataclass(frozen=True)
class GraphCandidate:
    # one paper produced by one graph signal, with the features that explain it

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

# Focused neighborhood for the graph panel. Fetch each direction with its own
# budget and return only the seed relationships the UI needs. The previous
# query expanded an undirected relationship from every selected neighbor and
# then filtered the result, doing avoidable work on highly cited papers.
_TWO_HOP_NEIGHBORHOOD = """
MATCH (seed:Paper {id: $paper_id})
CALL {
  WITH seed
  OPTIONAL MATCH (seed)-[:CITES]->(reference:Paper)
  WITH reference ORDER BY reference.cited_by_count DESC
  LIMIT $per_hop
  RETURN [node IN collect(reference) WHERE node IS NOT NULL] AS references
}
CALL {
  WITH seed
  OPTIONAL MATCH (citer:Paper)-[:CITES]->(seed)
  WITH citer ORDER BY citer.cited_by_count DESC
  LIMIT $per_hop
  RETURN [node IN collect(citer) WHERE node IS NOT NULL] AS citers
}
RETURN seed, references, citers
"""

async def direct_neighbors(
    driver: AsyncDriver, paper_ids: list[str], limit: int = 20
) -> list[GraphCandidate]:
    """one undirected hop from the seeds, single hop undirected is safe
    only variable len undirected expansion is a trap"""

    if not paper_ids:
        return []
    records, _, _ = await driver.execute_query(
        _DIRECT_NEIGHBORS, paper_ids=paper_ids, limit=limit
    )

    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["seed_links"]),
            signal="citation_neighbors",
            features={"seed_links": r["seed_links"], "min_graph_distance": 1},
        )
        for r in records
    ]


# fix: this function was missing — the Cypher constant existed but retrieval/graph_search.py
# and agent/tools.py call queries.bibliographic_coupling, which raised AttributeError
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


def _node_dict(node, is_seed: bool = False, role: str | None = None) -> dict:
    return {
        "id": node["id"],
        "title": node.get("title"),
        "year": node.get("year"),
        "cited_by_count": node.get("cited_by_count") or 0,
        "is_stub": bool(node.get("is_stub")),
        "is_seed": is_seed,
        "role": role or ("seed" if is_seed else "related"),
    }


async def two_hop_neighborhood(driver: AsyncDriver, paper_id: str, per_hop: int = 15) -> dict:
    """Nodes + edges for the graph panel: seed, capped hop-1 papers in both dirs
    and every CITES edge amount thar node set"""

    records, _, _ = await driver.execute_query(
        _TWO_HOP_NEIGHBORHOOD, paper_id=paper_id, per_hop=per_hop
    )

    if not records:
        return {
            "nodes": [],
            "edges": [],
            "stats": {"total_neighbors": 0, "visible_neighbors": 0, "hidden_stubs": 0},
        }

    record = records[0]
    seed_id = record["seed"]["id"]
    references = list(record["references"])
    citers = list(record["citers"])

    related: dict[str, dict] = {}
    for node in references:
        related[node["id"]] = _node_dict(node, role="reference")
    for node in citers:
        node_id = node["id"]
        role = "both" if node_id in related else "citer"
        related[node_id] = _node_dict(node, role=role)

    edges = [
        {"source": seed_id, "target": node["id"], "type": "CITES"}
        for node in references
    ]
    edges += [
        {"source": node["id"], "target": seed_id, "type": "CITES"}
        for node in citers
    ]

    nodes = [_node_dict(record["seed"], is_seed=True), *related.values()]
    hidden_stubs = sum(1 for node in related.values() if node["is_stub"] or not node["title"])
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_neighbors": len(related),
            "visible_neighbors": len(related) - hidden_stubs,
            "hidden_stubs": hidden_stubs,
        },
    }
