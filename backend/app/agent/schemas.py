# Any is used for arbitrary JSON-like error details.
from typing import Any, Literal
# UUID gives typed IDs in tool inputs/outputs.
from uuid import UUID

# BaseModel validates tool JSON; Field adds defaults and bounds.
from pydantic import BaseModel, Field


class ToolError(Exception):
    """Structured tool failure. Flows back into the agent conversation so the
    model can correct itself and retry."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        # Exception text is model/user-readable.
        super().__init__(message)
        # Stable machine-readable code like "not_found" or "invalid_arguments".
        self.code = code
        self.message = message
        self.details = details or {}

    def as_tool_result(self) -> dict[str, Any]:
        # Tool errors become data passed back to the LLM so it can self-correct.
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


class SearchPapersInput(BaseModel):
    query: str
    source: Literal["local", "openalex"] = "openalex"
    year_min: int | None = None
    year_max: int | None = None
    limit: int = Field(default=10, ge=1, le=50)


class PaperSearchResult(BaseModel):
    paper_id: UUID | None = None
    external_id: str | None = None
    title: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    cited_by_count: int = 0
    imported: bool = False


class SearchPapersOutput(BaseModel):
    papers: list[PaperSearchResult]
    summary: str = ""


class ImportPaperInput(BaseModel):
    source: Literal["openalex"]
    source_id: str
    project_id: UUID


class ImportPaperOutput(BaseModel):
    job_id: UUID
    status: Literal["queued"]
    summary: str = "paper import queued"


class GetPaperInput(BaseModel):
    paper_id: UUID
    project_id: UUID | None = None


class GetPaperOutput(BaseModel):
    paper: dict
    summary: str = "paper loaded"


class CitationNeighborhoodInput(BaseModel):
    paper_id: UUID
    per_hop: int = Field(default=15, ge=1, le=50)
    include_shared_concepts: bool = True


class CitationNeighborhoodOutput(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    ranked_neighbors: list[dict] = Field(default_factory=list)
    summary: str = "citation neighborhood loaded"


class RetrieveEvidenceInput(BaseModel):
    project_id: UUID
    query: str
    seed_paper_ids: list[UUID] | None = None
    limit: int = Field(default=10, ge=1, le=30)


class EvidenceItem(BaseModel):
    paper_id: UUID
    title: str | None
    chunk_id: UUID | None = None
    text: str | None = None
    score: float
    retrieval_sources: list[str]
    reason: str
    in_project: bool
    is_stub: bool


class RetrieveEvidenceOutput(BaseModel):
    evidence: list[EvidenceItem]
    summary: str


class RankRelatedWorkInput(BaseModel):
    project_id: UUID
    section_text: str
    limit: int = Field(default=8, ge=1, le=20)


class RelatedWorkRecommendation(BaseModel):
    paper_id: UUID
    bibtex_key: str | None = None
    title: str | None
    reason: str
    evidence_snippets: list[str] = Field(default_factory=list)
    score: float
    is_stub: bool


class RankRelatedWorkOutput(BaseModel):
    recommendations: list[RelatedWorkRecommendation]
    summary: str


class SuggestBibtexInput(BaseModel):
    paper_ids: list[UUID]
    project_id: UUID


class BibtexEntry(BaseModel):
    paper_id: UUID
    bibtex_key: str
    bibtex: str


class SuggestBibtexOutput(BaseModel):
    entries: list[BibtexEntry]
    summary: str


class InspectLatexProjectInput(BaseModel):
    project_id: UUID
    paths: list[str] | None = None


class LatexFileView(BaseModel):
    path: str
    content: str
    version: int


class InspectLatexProjectOutput(BaseModel):
    files: list[LatexFileView]
    summary: str


class PatchLatexFileInput(BaseModel):
    project_id: UUID
    patch: dict  # validated against latex.patcher.Patch inside the tool


class PatchLatexFileOutput(BaseModel):
    status: str
    new_version: int | None = None
    summary: str


class CompileLatexInput(BaseModel):
    project_id: UUID
    main_file_path: str = "main.tex"


class CompileLatexOutput(BaseModel):
    compilation_id: UUID
    status: Literal["queued"]
    summary: str = "latex compilation queued"