from neo4j import AsyncDriver

from app.graph import queries
from app.graph.queries import GraphCandidate


class GraphSearch:
    def __init__(self, driver: AsyncDriver):
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
