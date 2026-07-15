# tools registered once with name, description (the model reads this, a vague description is a routing bug) 
# pydantic input/models and the implementation
# spec() derives JSON schema from the input models, so validation and documentation cannot drift apart
# the web agent and MCP consume this same registry

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pydantic import BaseModel, ValidationError

from app.agent import schemas as s
from app.agent import tools
from app.agent.llm.base import ToolSpec
from app.agent.schemas import ToolError
from app.agent.tools import ToolContext

@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    fn: Callable[[ToolContext, BaseModel], Awaitable[BaseModel]]


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        
        self._tools[definition.name] = definition

    def names(self) -> list[str]:
        return sorted(self._tools)

    def is_project_scoped(self, name: str) -> bool:
        # true when the tool's input model takes a project_id, so the
        # orchestrator can pin it to the active project instead of trusting
        # a model-provided (possibly hallucinated) id
        definition = self._tools.get(name)
        return definition is not None and "project_id" in definition.input_model.model_fields
    
    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=d.name, 
                description=d.description,
                input_schema=d.input_model.model_json_schema(),
            )
            for d in self._tools.values()
        ]
    
    async def execute(self, name: str, arguments: dict) -> BaseModel:
        # find registered tool by model requested name
        definition = self._tools.get(name)

        if definition is None:
            raise ToolError("unknown_tool", f"No tool named '{name}'. Available: {self.names()}")
        try:
            # validate raw JSON args before executing Python code
            args = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError(
                "invalid_arguments",
                f"Arguments for '{name}' failed validation: {exc.errors()[:3]}",
            )
        return await definition.fn(self.ctx, args)
    
def build_default_registry(ctx: ToolContext) -> ToolRegistry:
    registry = ToolRegistry(ctx)
    for definition in [
        ToolDefinition(
            name="search_papers",
            description=(
                "Search scholarly papers. source='openalex' searches the global OpenAlex "
                "index; source='local' searches papers already imported into CitePilot. "
                "Returns titles, years, authors, abstracts, citation counts, and whether "
                "each paper is already imported."
            ),
            input_model=s.SearchPapersInput,
            output_model=s.SearchPapersOutput,
            fn=tools.search_papers,
        ),
        ToolDefinition(
            name="import_paper",
            description=(
                "Import a paper by its OpenAlex ID into the project. Stores metadata, "
                "creates stub records for all its references, mirrors the citation graph, "
                "and embeds the abstract. Returns a job_id to poll."
            ),
            input_model=s.ImportPaperInput,
            output_model=s.ImportPaperOutput,
            fn=tools.import_paper,
        ),
        ToolDefinition(
            name="get_paper",
            description="Fetch one imported paper's full metadata, authors, concepts, and whether it is in the project.",
            input_model=s.GetPaperInput,
            output_model=s.GetPaperOutput,
            fn=tools.get_paper,
        ),
        ToolDefinition(
            name="get_citation_neighborhood",
            description=(
                "Explore the local citation graph around a paper: nodes/edges for "
                "visualization plus neighbors ranked by co-citation, shared references, "
                "and shared concepts, each with a human-readable reason."
            ),
            input_model=s.CitationNeighborhoodInput,
            output_model=s.CitationNeighborhoodOutput,
            fn=tools.get_citation_neighborhood,
        ),
        ToolDefinition(
            name="retrieve_evidence",
            description=(
                "Hybrid GraphRAG retrieval for a query or paragraph: fuses semantic "
                "similarity with citation-graph signals (co-citation, bibliographic "
                "coupling, shared concepts). Use this to find citation-worthy papers. "
                "Returns ranked evidence with supporting text and reasons."
            ),
            input_model=s.RetrieveEvidenceInput,
            output_model=s.RetrieveEvidenceOutput,
            fn=tools.retrieve_evidence,
        ),
        ToolDefinition(
            name="rank_related_work",
            description=(
                "Recommend citations for a LaTeX section or paragraph. Runs hybrid "
                "retrieval on the text and returns ranked recommendations with reasons, "
                "evidence snippets, and BibTeX keys for papers already in the project."
            ),
            input_model=s.RankRelatedWorkInput,
            output_model=s.RankRelatedWorkOutput,
            fn=tools.rank_related_work,
        ),
        ToolDefinition(
            name="suggest_bibtex",
            description=(
                "Produce BibTeX entries (Crossref publisher data when a DOI exists, "
                "escaped fallback otherwise) and stable citation keys for papers, "
                "linking them to the project. Use the returned keys in \\cite{}."
            ),
            input_model=s.SuggestBibtexInput,
            output_model=s.SuggestBibtexOutput,
            fn=tools.suggest_bibtex,
        ),
        ToolDefinition(
            name="inspect_latex_project",
            description="Read the project's LaTeX files (optionally specific paths). Returns path, content, and version for each.",
            input_model=s.InspectLatexProjectInput,
            output_model=s.InspectLatexProjectOutput,
            fn=tools.inspect_latex_project,
        ),
        ToolDefinition(
            name="patch_latex_file",
            description=(
                "Edit a project file with an anchor-based patch: either "
                "{operation:'replace_text', path, base_version, old_text, new_text} or "
                "{operation:'insert_after', path, base_version, anchor_text, new_text}. "
                "The anchor must occur exactly once in the current file content."
            ),
            input_model=s.PatchLatexFileInput,
            output_model=s.PatchLatexFileOutput,
            fn=tools.patch_latex_file,
        ),
        ToolDefinition(
            name="compile_latex",
            description="Compile the project's LaTeX to PDF with Tectonic. Returns a compilation_id to poll for status, logs, and the PDF.",
            input_model=s.CompileLatexInput,
            output_model=s.CompileLatexOutput,
            fn=tools.compile_latex,
        ),
    ]:
        registry.register(definition)
    return registry