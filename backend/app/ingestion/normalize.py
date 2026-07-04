# every source converges into NormalizedPaper before touching storage
import re
from pydantic import BaseModel, Field

class NormalizedAuthor(BaseModel):
    source_id: str | None = None
    name: str
    order: int | None = None

class NormalizedConcept(BaseModel):
    # Normalized concept/topic/method name.
    name: str
    # MVP defaults to generic concept; future values include method/dataset/task.
    type: str = "concept"
    # Provider confidence/relevance score.
    score: float | None = None
    # Where the concept came from, e.g. openalex.
    source: str


class NormalizedPaper(BaseModel):
    source: str                      # 'openalex' | 'semantic_scholar' | 'crossref'
    source_id: str
    title: str | None = None
    doi: str | None = None           # already normalized
    abstract: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    venue_name: str | None = None
    cited_by_count: int | None = None
    url: str | None = None
    pdf_url: str | None = None
    authors: list[NormalizedAuthor] = Field(default_factory=list)
    concepts: list[NormalizedConcept] = Field(default_factory=list)
    reference_source_ids: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


def normalize_doi(raw: str | None) -> str | None:
    """Apply before ANY read or write of a DOI."""
    if not raw:
        # Treat empty/missing DOI as no DOI.
        return None
    # Remove surrounding whitespace.
    doi = raw.strip()
    # Strip common DOI URL prefixes.
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    # DOI matching is case-insensitive, so store lowercase.
    return doi.lower() or None


def normalize_title_for_match(title: str | None) -> str | None:
    """Lowercase, alphanumeric-only, collapsed whitespace — the last-resort dedup key."""
    if not title:
        return None
    # Convert punctuation/dashes/etc. to spaces and lowercase.
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    # Empty string after normalization means there is no usable title key.
    return normalized or None


def reconstruct_openalex_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    # OpenAlex stores word -> positions; flatten into (position, word).
    positions = [(i, word) for word, idxs in inv.items() for i in idxs]
    # Sort by position to recover the original abstract text.
    return " ".join(word for _, word in sorted(positions))


def _openalex_authors(work: dict) -> list[NormalizedAuthor]:
    # Convert OpenAlex authorships into normalized authors.
    authors: list[NormalizedAuthor] = []
    for order, authorship in enumerate(work.get("authorships") or [], start=1):
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(NormalizedAuthor(source_id=author.get("id"), name=name, order=order))
    return authors


def _openalex_concepts(work: dict) -> list[NormalizedConcept]:
    # Convert OpenAlex concepts/topics into normalized concept DTOs.
    concepts: list[NormalizedConcept] = []
    for concept in work.get("concepts") or []:
        name = concept.get("display_name")
        if name:
            concepts.append(
                NormalizedConcept(name=name, score=concept.get("score"), source="openalex")
            )
    if not concepts:  # newer OpenAlex records use topics instead of concepts
        for topic in work.get("topics") or []:
            name = topic.get("display_name")
            if name:
                concepts.append(
                    NormalizedConcept(name=name, score=topic.get("score"), source="openalex")
                )
    return concepts[:10]


def normalize_openalex_work(work: dict) -> NormalizedPaper:
    # Defensive `or {}` handles OpenAlex null sub-objects.
    primary_location = work.get("primary_location") or {}
    location_source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    # Return one provider-neutral DTO; storage code never sees raw provider shapes.
    return NormalizedPaper(
        source="openalex",
        source_id=work["id"],
        title=work.get("display_name") or work.get("title"),
        doi=normalize_doi(work.get("doi")),
        abstract=reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
        publication_year=work.get("publication_year"),
        publication_date=work.get("publication_date"),
        venue_name=location_source.get("display_name"),
        cited_by_count=work.get("cited_by_count"),
        url=work["id"],
        pdf_url=open_access.get("oa_url"),
        authors=_openalex_authors(work),
        concepts=_openalex_concepts(work),
        reference_source_ids=list(dict.fromkeys(work.get("referenced_works") or [])),
        raw=work,
    )