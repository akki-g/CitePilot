# first hit wins: norm DOI -> openalex_id -> semantic_scholar_id -> norm title + year 
# on match enrich the existing row 

from __future__ import annotations

from datetime import date
from uuid import UUID

#select reads exisiting rows; pg_insert enables ON CONFLICT helpers
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Author,
    Citation,
    Concept,
    Paper,
    PaperAuthor,
    PaperChunk,
    PaperConcept,
    ProjectPaper,
)

from app.ingestion.bibtex import BibtexPaper, generate_bibtex_key
from app.ingestion.normalize import NormalizedAuthor, NormalizedConcept, NormalizedPaper, normalize_title_for_match

from app.logging import get_logger
from app.retrieval.chunking import build_title_abstract_chunk

log = get_logger(__name__)

async def find_existing_paper(session: AsyncSession, np: NormalizedPaper) -> Paper | None:
    # best match: doi becaude its cross provider and normalized

    if np.doi:
        paper = (
            await session.execute(select(Paper).where(Paper.doi == np.doi))
        )
        if paper:
            return paper
    
    if np.source == "openalex":
        # Next best: provider-specific ID for the current source.
        paper = (
            await session.execute(select(Paper).where(Paper.openalex_id == np.source_id))
        ).scalar_one_or_none()
        if paper:
            return paper
    if np.source == "semantic_scholar":
        # Same idea for Semantic Scholar imports/enrichment.
        paper = (
            await session.execute(select(Paper).where(Paper.semantic_scholar_id == np.source_id))
        ).scalar_one_or_none()
        if paper:
            return paper
        
    match_title = normalize_title_for_match(np.title)
    if match_title and np.publication_year:
        candidates = (
            await session.execute(
                select(Paper).where(
                    Paper.publication_year == np.publication_year,
                    Paper.title.is_not(None),
                )
            )
        ).scalars()
        for candidate in candidates:
            if normalize_title_for_match(candidate.title) == match_title:
                return candidate
    return None

def _enrich(paper: Paper, np: NormalizedPaper) -> None:
    """Fill nulls, refresh volatile fields, never downgrade existing data."""
    if np.source == "openalex" and paper.openalex_id is None:
        paper.openalex_id = np.source_id
    if np.source == "semantic_scholar" and paper.semantic_scholar_id is None:
        paper.semantic_scholar_id = np.source_id
    if paper.doi is None and np.doi:
        paper.doi = np.doi
    if paper.title is None and np.title:
        paper.title = np.title
    if paper.abstract is None and np.abstract:
        paper.abstract = np.abstract
    if paper.publication_year is None:
        paper.publication_year = np.publication_year
    if paper.publication_date is None and np.publication_date:
        try:
            paper.publication_date = date.fromisoformat(np.publication_date)
        except ValueError:
            pass
    if paper.venue_name is None:
        paper.venue_name = np.venue_name
    if paper.url is None:
        paper.url = np.url
    if paper.pdf_url is None:
        paper.pdf_url = np.pdf_url
    if np.cited_by_count is not None:
        paper.cited_by_count = np.cited_by_count
    paper.is_stub = False

async def _upsert_author(session: AsyncSession, na: NormalizedAuthor) -> Author:
    if na.source_id:
        author = (
            await session.execute(select(Author).where(Author.openalex_id == na.source_id))
        ).scalar_one_or_none()

        if author:
            return author
        
    author = (
        # Fallback by name is imperfect but acceptable for POC metadata.
        await session.execute(select(Author).where(Author.name == na.name))
    ).scalars().first()
    if author:
        if author.openalex_id is None and na.source_id:
            author.openalex_id = na.source_id
        return author
    author = Author(openalex_id=na.source_id, name=na.name)
    session.add(author)
    await session.flush()
    return author

async def _link_authors(session: AsyncSession, paper: Paper, authors: list[NormalizedAuthor]) -> None:
    for na in authors:
        author = await _upsert_author(session, na)
        await session.execute(
            pg_insert(PaperAuthor)
            .values(paper_id=paper.id, author_id=author.id, author_order=na.order)
            .on_conflict_do_nothing(index_elements=["paper_id", "author_id"])
        )


async def _link_concepts(session: AsyncSession, paper: Paper, concepts: list[NormalizedConcept]) -> None:
     for nc in concepts:
        concept = (
            await session.execute(select(Concept).where(Concept.name == nc.name))
        ).scalar_one_or_none()
        if concept is None:
            concept = Concept(name=nc.name, type=nc.type)
            session.add(concept)
            await session.flush()
        await session.execute(
            pg_insert(PaperConcept)
            .values(paper_id=paper.id, concept_id=concept.id, score=nc.score, source=nc.source)
            .on_conflict_do_nothing(index_elements=["paper_id", "concept_id"])
        )

async def upsert_paper(session: AsyncSession, np: NormalizedPaper) -> Paper:
    # Try dedup match before inserting.
    paper = await find_existing_paper(session, np)
    created = paper is None
    if paper is None:
        # New canonical paper row.
        paper = Paper(is_stub=False)
        session.add(paper)
    _enrich(paper, np)
    # Flush assigns UUIDs before link tables reference the paper.
    await session.flush()
    await _link_authors(session, paper, np.authors)
    await _link_concepts(session, paper, np.concepts)
    log.info("paper.upsert", paper_id=str(paper.id), created=created, source=np.source)
    return paper

async def upsert_references_as_stubs(
    session: AsyncSession, citing: Paper, reference_source_ids: list[str]
) -> list[Paper]:
    """Create bare is_stub rows for unknown references and idempotent citation edges.

    Returns every cited Paper row (stub or full) so the caller can mirror them to Neo4j.
    """
    refs = [r for r in dict.fromkeys(reference_source_ids) if r]
    if not refs:
        return []
    existing = {
        p.openalex_id: p
        for p in (
            await session.execute(select(Paper).where(Paper.openalex_id.in_(refs)))
        ).scalars()
    }
    new_stubs = [Paper(openalex_id=ref, is_stub=True) for ref in refs if ref not in existing]
    # Add unknown references as placeholder papers.
    session.add_all(new_stubs)
    await session.flush()

    cited = list(existing.values()) + new_stubs
    # Create directed citation edges from the imported paper to every reference.
    edge_values = [
        {"citing_paper_id": citing.id, "cited_paper_id": p.id} for p in cited if p.id != citing.id
    ]
    if edge_values:
        await session.execute(
            pg_insert(Citation)
            .values(edge_values)
            .on_conflict_do_nothing(index_elements=["citing_paper_id", "cited_paper_id"])
        )
    log.info("paper.stubs", citing_id=str(citing.id), stubs_created=len(new_stubs), edges=len(edge_values))
    return cited

async def create_title_abstract_chunk(session: AsyncSession, paper: Paper) -> None:
    # Build one semantic chunk from whatever title/abstract data exists.
    chunk = build_title_abstract_chunk(paper.title, paper.abstract)
    if chunk is None:
        return
    existing = (
        await session.execute(
            select(PaperChunk).where(PaperChunk.paper_id == paper.id, PaperChunk.chunk_index == 0)
        )
    ).scalar_one_or_none()
    if existing:
        if existing.text != chunk.text:      # e.g. stub promoted: abstract arrived
            existing.text = chunk.text
            existing.token_count = chunk.token_count
            existing.embedding = None        # force re-embed
        return
    session.add(
        PaperChunk(
            paper_id=paper.id,
            chunk_index=0,
            section=chunk.section,
            text=chunk.text,
            token_count=chunk.token_count,
        )
    )

async def link_project_paper(session: AsyncSession, project_id: UUID, paper: Paper) -> str:
    """Attach a paper to a project with a stable, collision-free BibTeX key."""
    existing = (
        await session.execute(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id, ProjectPaper.paper_id == paper.id
            )
        )
    ).scalar_one_or_none()
    if existing:
        # Reuse stable key if the paper is already in this project.
        return existing.bibtex_key

    author_names = [
        row[0]
        for row in (
            await session.execute(
                select(Author.name)
                .join(PaperAuthor, PaperAuthor.author_id == Author.id)
                .where(PaperAuthor.paper_id == paper.id)
                .order_by(PaperAuthor.author_order)
            )
        ).all()
    ]
    existing_keys = {
        row[0]
        for row in (
            await session.execute(
                select(ProjectPaper.bibtex_key).where(ProjectPaper.project_id == project_id)
            )
        ).all()
    }
    key = generate_bibtex_key(
        BibtexPaper(
            title=paper.title,
            publication_year=paper.publication_year,
            venue_name=paper.venue_name,
            doi=paper.doi,
            url=paper.url,
            authors=author_names,
        ),
        existing_keys,
    )
    session.add(ProjectPaper(project_id=project_id, paper_id=paper.id, bibtex_key=key))
    await session.flush()
    return key


async def ingest_normalized_paper(
    session: AsyncSession, np: NormalizedPaper
) -> tuple[Paper, list[Paper]]:
    """Upsert paper + stub references + chunk. Project linking is separate on
    purpose — stub promotion enriches a paper without adding it to any project."""
    paper = await upsert_paper(session, np)
    cited = await upsert_references_as_stubs(session, paper, np.reference_source_ids)
    await create_title_abstract_chunk(session, paper)
    return paper, cited