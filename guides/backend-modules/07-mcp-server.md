# Module Guide: MCP Server

Files in this guide (all complete — type them as-is):

- `backend/app/mcp_server/server.py`
- `backend/app/mcp_server/tools.py` ⭐ core learning file

**Why this module:** the same ten tools that power the in-app agent, exposed to any MCP client (Claude Desktop, MCP Inspector, Cursor) with **zero duplicated logic** — every wrapper builds the same Pydantic input model and calls the same `app.agent.tools` function. Capabilities are a layer; agents and protocols are consumers.

Transport is **stdio only**: the client launches the server as a subprocess, so it's inherently local. Exposing it over Streamable HTTP is a security boundary, not a config change — the server has full database access and would need real auth first.

MCP clients show your docstrings to the model **verbatim** — the docstring *is* the interface. Write them for a model reader: what it does, what inputs mean, what comes back, when to use it.

**Comment style:** MCP wrappers are intentionally boring. The comments point out where lifecycle, validation, logging, and model-facing descriptions happen.

---

## `backend/app/mcp_server/server.py`

```python
# FastMCP is the official SDK helper for declaring MCP tools.
from mcp.server.fastmcp import FastMCP

# register_tools attaches all CitePilot tools to the MCP server.
from app.mcp_server.tools import register_tools

# Create one local stdio MCP server named "citepilot".
mcp = FastMCP("citepilot")
# Register tool wrappers at import time.
register_tools(mcp)

if __name__ == "__main__":
    # stdio transport: MCP client launches this process and speaks over stdin/stdout.
    mcp.run()   # stdio transport
```

Add the MCP SDK to `backend/pyproject.toml` dependencies and rebuild:

```toml
    # Official MCP Python SDK.
    "mcp>=1.2",
```

## ⭐ `backend/app/mcp_server/tools.py`

`MCPRuntime` owns process-wide clients (the server runs outside FastAPI, so it builds its own). `_run` gives every wrapper the same behavior: fresh DB session per call, `ToolError` returned as structured data instead of a crash, and every call logged to `tool_calls` with `session_id = NULL` — MCP calls show up in the same observability table as web-agent calls.

```python
# Future annotations keep type hints flexible.
from __future__ import annotations

# asynccontextmanager gives each tool call a fresh DB session.
import contextlib
# UTC timestamps mark tool-call completion.
from datetime import UTC, datetime

# Redis client for cache/external clients.
import redis.asyncio as aioredis
# arq pool lets MCP tools enqueue jobs, same as web tools.
from arq import create_pool
# ArqRedis/RedisSettings types configure the queue pool.
from arq.connections import ArqRedis, RedisSettings
# FastMCP tool decorator.
from mcp.server.fastmcp import FastMCP

# Shared Pydantic schemas and core tool implementations.
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
        # MCP runs outside FastAPI, so it creates the same clients FastAPI lifespan creates.
        self.settings = get_settings()
        self.engine = create_engine(self.settings)
        self.session_factory = create_session_factory(self.engine)
        self.neo4j = create_neo4j_driver(self.settings)
        self.redis = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self._arq_pool: ArqRedis | None = None

    async def arq_pool(self) -> ArqRedis:
        # arq pool creation is async, so lazy-create it on first job-producing tool call.
        if self._arq_pool is None:   # async creation, so lazily on first use
            self._arq_pool = await create_pool(RedisSettings.from_dsn(self.settings.REDIS_URL))
        return self._arq_pool

    @contextlib.asynccontextmanager
    async def tool_context(self):
        # Every MCP tool call gets its own DB session.
        async with self.session_factory() as session:
            # Build the same ToolContext the web agent uses.
            yield ToolContext(
                session, self.settings, self.neo4j, self.redis, await self.arq_pool()
            )


runtime = MCPRuntime()


async def _run(fn, args) -> dict:
    """One code path for every wrapper: session, logging, structured errors."""
    async with runtime.tool_context() as ctx:
        # Log MCP calls in the same tool_calls table as web-agent calls.
        record = ToolCallRecord(
            session_id=None, tool_name=fn.__name__, arguments=args.model_dump(mode="json")
        )
        ctx.session.add(record)
        await ctx.session.commit()
        try:
            # Execute the shared core implementation.
            output = await fn(ctx, args)
        except ToolError as exc:
            # Return structured tool errors instead of crashing the MCP server.
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
```

MCP walkthrough:

- `server.py` owns the MCP server object; `tools.py` owns tool registration.
- `MCPRuntime` replaces FastAPI lifespan for this standalone process.
- `_run()` is the shared wrapper pattern: session, audit log, execute, structured error/result.
- Every MCP wrapper should be thin: build schema, call core tool, return JSON.
- Tool docstrings are prompts. Bad docstrings cause bad model routing.

Safety rules baked in (be ready to list them): no arbitrary SQL/Cypher/shell tools, everything project-scoped and typed through the same Pydantic models as the web agent, list sizes capped by the input models (`le=` bounds), stdio only.

## Running it

**MCP Inspector** (from the repo root, with compose up):

```bash
npx @modelcontextprotocol/inspector docker compose exec -T backend python -m app.mcp_server.server
```

Command walkthrough:

- `npx @modelcontextprotocol/inspector`: launches MCP Inspector.
- `docker compose exec -T backend`: runs the MCP server inside the backend container without a TTY.
- `python -m app.mcp_server.server`: starts the stdio MCP server.

**Claude Desktop** — `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "citepilot": {
      "command": "docker",
      "args": [
        "compose", "-f", "/ABSOLUTE/PATH/TO/citepilot/docker-compose.yml",
        "exec", "-T", "backend",
        "python", "-m", "app.mcp_server.server"
      ]
    }
  }
}
```

Config walkthrough:

- `command: "docker"` tells Claude Desktop to launch Docker as the MCP subprocess.
- `compose -f ... exec -T backend ...` attaches stdio to the backend container's Python process.
- `-T` matters because MCP stdio must be a clean pipe, not an interactive terminal.

(`-T` disables the TTY so stdio stays a clean pipe. Replace the absolute path.)

## Acceptance checks

- Inspector lists exactly ten tools with their docstrings.
- `search_papers`, `get_citation_neighborhood`, and `retrieve_evidence` succeed end-to-end.
- Each call appears in the `tool_calls` table with `session_id IS NULL`.
- Claude Desktop can drive an import: search → import_paper → (wait) → get_paper.
