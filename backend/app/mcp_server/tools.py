from __future__ import annotations

import contextlib

from datetime import UTC, datetime
import redis.asyncio as aioredis

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from mcp.server.fastmcp import FastMCP

from app.agent import schemas as s
from app.agent import tools as core
from app.agent.schemas import ToolError
from app.agent.tools import ToolContext
from app.config import get_settings
from app.db.models import ToolCallRecord
from app.db.postgres import create_engine, create_session_factory
from app.graph.neo4j_client import create_neo4j_driver


class MCPRuntime:
    def __init__(self):
        # mcp runs outside of fastapi so it creates the same clients fastapi lifespan creates
        self.settings = get_settings()
        self.engine = create_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)
        self.neo4j = create_neo4j_driver(self.settings)
        self.redis = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self._arq_pool: ArqRedis | None = None
    
    async def arq_pool(self) -> ArqRedis:
        # arq pool create is async so lazy create it on first job producing tool call
        if self._arq_pool is None:
            self._arq_pool = await create_pool(RedisSettings.from_dsn(self.settings.REDIS_URL))
        return self._arq_pool
    
    @contextlib.asynccontextmanager
    async def tool_context(self):
        # every mcp tool call gets its own DM session
        async with self.session_factory() as session:
            # build the same tool context the web agent uses
            yield ToolContext(
                session, self.settings, self.neo4j, self.redis, await self.arq_pool()
            )


runtime = MCPRuntime()

async def _run(fn, args) -> dict:
    # one code path for every wrapper: session, logging, structured errors
    async with runtime.tool_context() as ctx:
        # log MCP calls in the same tool_calls table as web_agent calls
        record = ToolCallRecord(
            session_id=None, tool_name=fn.__name__, arguments=args.model_dump(mode="json")
        )
        ctx.session.add(record)
        await ctx.session.commit()

        try:
            # execute the shared core implementation
            output = await fn(ctx, args)
        except ToolError as exc:
            # return structured tool errors instead of crashing the MCP server
            record.status = "failed"
            record.error = f"{exc.code}: {exc.message}"
            record.completed_at = datetime.now(UTC)
            await ctx.session.commit()
            return exc.as_tool_result()
        payload = output.model_dump(mode="json")
        # Store only a small summary for MCP calls.
        record.status = "completed"
        record.result = {"summary": payload.get("summary", "ok")}
        record.completed_at = datetime.now(UTC)
        await ctx.session.commit()
        return payload


def register_tools(mcp: FastMCP) -> None:
    # Each decorated function becomes one MCP tool. The docstring is shown to the model.
    @mcp.tool()
    async def search_papers(
        query: str,
        source: str = "openalex",
        year_min: int | None = None,
        year_max: int | None = None,
        limit: int = 10,
    ) -> dict:
        """Search scholarly papers. source='openalex' searches the global OpenAlex
        index; source='local' searches papers already imported into CitePilot.
        Returns titles, years, authors, abstracts, citation counts, and whether
        each paper is already imported."""
        return await _run(
            # Wrapper builds validated Pydantic input, then delegates to core tool.
            core.search_papers,
            s.SearchPapersInput(
                query=query, source=source, year_min=year_min, year_max=year_max, limit=limit
            ),
        )

    @mcp.tool()
    async def import_paper(source_id: str, project_id: str, source: str = "openalex") -> dict:
        """Import a paper by OpenAlex ID into a CitePilot project. Stores metadata,
        creates stub records for every reference, mirrors the citation graph, and
        embeds the abstract. Returns a job_id; the import runs asynchronously."""
        return await _run(
            core.import_paper,
            s.ImportPaperInput(source=source, source_id=source_id, project_id=project_id),
        )

    @mcp.tool()
    async def get_paper(paper_id: str, project_id: str | None = None) -> dict:
        """Fetch one imported paper's full metadata: title, abstract, year, venue,
        authors, concepts, citation count, and whether it is in the given project."""
        return await _run(core.get_paper, s.GetPaperInput(paper_id=paper_id, project_id=project_id))

    @mcp.tool()
    async def get_citation_neighborhood(
        paper_id: str, per_hop: int = 15, include_shared_concepts: bool = True
    ) -> dict:
        """Explore the local citation graph around a paper. Returns nodes/edges for
        visualization plus neighbors ranked by co-citation, shared references, and
        shared concepts, each with a human-readable reason."""
        return await _run(
            core.get_citation_neighborhood,
            s.CitationNeighborhoodInput(
                paper_id=paper_id, per_hop=per_hop, include_shared_concepts=include_shared_concepts
            ),
        )

    @mcp.tool()
    async def retrieve_evidence(
        project_id: str, query: str, seed_paper_ids: list[str] | None = None, limit: int = 10
    ) -> dict:
        """Hybrid GraphRAG retrieval for a research-writing query: fuses semantic
        similarity with citation-graph signals (co-citation, bibliographic coupling,
        shared concepts) via Reciprocal Rank Fusion. Use this to find citation-worthy
        papers for a paragraph. Returns ranked evidence with supporting snippets,
        retrieval sources, and reasons."""
        return await _run(
            core.retrieve_evidence,
            s.RetrieveEvidenceInput(
                project_id=project_id, query=query, seed_paper_ids=seed_paper_ids, limit=limit
            ),
        )

    @mcp.tool()
    async def rank_related_work(project_id: str, section_text: str, limit: int = 8) -> dict:
        """Recommend citations for a LaTeX section or paragraph. Returns ranked
        recommendations with reasons, evidence snippets, and BibTeX keys for papers
        already in the project (null for papers not yet linked)."""
        return await _run(
            core.rank_related_work,
            s.RankRelatedWorkInput(project_id=project_id, section_text=section_text, limit=limit),
        )

    @mcp.tool()
    async def suggest_bibtex(paper_ids: list[str], project_id: str) -> dict:
        """Produce BibTeX entries and stable citation keys for papers, linking them
        to the project. Uses publisher data via Crossref when a DOI exists, otherwise
        generates an escaped entry. Use the returned keys in \\\\cite{}."""
        return await _run(
            core.suggest_bibtex, s.SuggestBibtexInput(paper_ids=paper_ids, project_id=project_id)
        )

    @mcp.tool()
    async def inspect_latex_project(project_id: str, paths: list[str] | None = None) -> dict:
        """Read the project's LaTeX files (all files, or specific relative paths).
        Returns path, full content, and current version for each file. Read before
        patching — patches need exact current text and version."""
        return await _run(
            core.inspect_latex_project,
            s.InspectLatexProjectInput(project_id=project_id, paths=paths),
        )

    @mcp.tool()
    async def patch_latex_file(project_id: str, patch: dict) -> dict:
        """Edit a project file with an anchor-based patch. patch is either
        {operation:'replace_text', path, base_version, old_text, new_text} or
        {operation:'insert_after', path, base_version, anchor_text, new_text}.
        The anchor must occur exactly once in the current file content; base_version
        must match the file's current version (see inspect_latex_project)."""
        return await _run(
            core.patch_latex_file, s.PatchLatexFileInput(project_id=project_id, patch=patch)
        )

    @mcp.tool()
    async def compile_latex(project_id: str, main_file_path: str = "main.tex") -> dict:
        """Compile the project's LaTeX to PDF with Tectonic in a sandboxed worker.
        Returns a compilation_id; poll the web API for status, logs, and the PDF."""
        return await _run(
            core.compile_latex,
            s.CompileLatexInput(project_id=project_id, main_file_path=main_file_path),
        )