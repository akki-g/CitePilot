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

# two-hop neighborhood for the graph paned, capped per direction. the CASE/UNWIND
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
    """one undirected hop from the seeds, single hop undirected is safe
    only variable len undirected expansion is a trap"""

    if not paper_ids:
        return []
    
    records, _, _ = await driver.execute_query(_DIRECT_NEIGHBORS, paper_ids=paper_ids, limit=limit)

    return [
        GraphCandidate(
            paper_id=r["paper_id"],
            score=float(r["seed_links"]),
            signal="citation_neighbors",
            features={"seed_links": r["seed_links"], "min_graph_distance": 1}
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
    """Nodes + edges for the graph panel: seed, capped hop-1 papers in both dirs
    and every CITES edge amont thar node set"""

    records, _, _ = await driver.execute_query(
        _TWO_HOP_NEIGHBORHOOD, paper_id=paper_id, per_hop=per_hop
    )

    if not records:
        return {"nodes":[], "edges": []}
    
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
        edges.append({"source": edge["source"], "target": edge["target"], "type":"CITES"})

    return {"nodes": nodes, "edges": edges}

