from dataclasses import dataclass

from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

def to_pg_vector_literal(embedding: list[float]) -> str:
    # asyncpg cannot bind py lists as pgvector in raw text queries reliably
    # converting to "[...]" and CASTing in SQL makes the type explicit

    return "["+",".join(str(x) for x in embedding) + "]"

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
            {"query_embedding": to_pg_vector_literal(query_embedding), "limit": limit},
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
