# Module Guide: Tests and Fixtures

Files in this guide (all complete — type them as-is):

- `backend/app/tests/conftest.py`
- `backend/app/tests/test_health.py`
- `backend/app/tests/test_normalize.py`
- `backend/app/tests/test_bibtex.py`
- `backend/app/tests/test_fusion.py`
- `backend/app/tests/test_hybrid_retrieval.py`
- `backend/app/tests/test_latex_patcher.py`
- `backend/app/tests/test_path_sanitizer.py`
- `backend/app/tests/test_agent_stream.py`
- `backend/app/tests/fixtures/openalex_work.json`
- `backend/app/tests/fixtures/openalex_search.json`
- `backend/app/tests/fixtures/crossref_bibtex.txt`
- `backend/app/tests/fixtures/semantic_scholar_paper.json`

**Why this module:** these tests are executable specs for the ⭐ core files. The learning rhythm they enable: delete a core file, rewrite it from the guide, run its test — if it passes, you understood it. Hard rule: **no test ever calls OpenAlex, Crossref, Semantic Scholar, or an LLM provider** — fakes and fixtures only.

Pure unit tests (normalize, bibtex, fusion, sanitizer) run anywhere; the DB-backed ones (patcher, hybrid, agent stream) run inside the backend container against compose services. `asyncio_mode = "auto"` in `pyproject.toml` means async tests need no decorators.

**Comment style:** tests are documentation with teeth. The walkthroughs below explain which production bug each test is meant to catch.

---

## `backend/app/tests/conftest.py`

```python
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Project, User
from app.db.postgres import create_engine, create_session_factory
from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with LifespanManager(app):   # runs lifespan; plain ASGI transport would skip it
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session: AsyncSession) -> Project:
    """A project owned by the (idempotently created) dev user."""
    settings = get_settings()
    user = await db_session.get(User, UUID(settings.DEV_USER_ID))
    if user is None:
        user = User(
            id=UUID(settings.DEV_USER_ID), email="dev@citepilot.local", display_name="Dev User"
        )
        db_session.add(user)
        await db_session.flush()
    proj = Project(user_id=user.id, name="test-project")
    db_session.add(proj)
    await db_session.commit()
    return proj
```

Fixture walkthrough:

- `client`: creates the FastAPI app in-process and runs lifespan so `app.state` clients exist.
- `ASGITransport`: avoids real network sockets while exercising actual routes.
- `db_session`: gives tests direct DB access for setup/assertions.
- `project`: creates a real project row owned by the dev user, used by DB-backed tests.
- These fixtures deliberately avoid external APIs and LLM providers.

## `backend/app/tests/test_health.py`

```python
async def test_health_reports_all_services(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["neo4j"] == "ok"
    assert body["redis"] == "ok"
```

Test walkthrough:

- This is an integration smoke test for FastAPI lifespan and all three stores.
- If it fails, later backend tests probably cannot be trusted yet.
- It proves `/api/health` does real connectivity checks, not a hardcoded response.

## `backend/app/tests/test_normalize.py`

```python
import json
from pathlib import Path

from app.ingestion.normalize import (
    normalize_doi,
    normalize_openalex_work,
    normalize_title_for_match,
    reconstruct_openalex_abstract,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_doi_strips_url_and_lowercases():
    assert normalize_doi("https://doi.org/10.1145/ABC.Def") == "10.1145/abc.def"
    assert normalize_doi("http://dx.doi.org/10.1000/XYZ") == "10.1000/xyz"
    assert normalize_doi(" 10.1000/Foo ") == "10.1000/foo"
    assert normalize_doi(None) is None
    assert normalize_doi("") is None


def test_normalize_title_for_match():
    assert normalize_title_for_match("GraphRAG:  A Survey!") == "graphrag a survey"
    assert normalize_title_for_match("  ") is None
    assert normalize_title_for_match(None) is None


def test_reconstruct_openalex_abstract_orders_words():
    inv = {"world": [1], "hello": [0], "again": [2]}
    assert reconstruct_openalex_abstract(inv) == "hello world again"
    assert reconstruct_openalex_abstract(None) is None
    assert reconstruct_openalex_abstract({}) is None


def test_normalize_openalex_work_fixture():
    work = json.loads((FIXTURES / "openalex_work.json").read_text())
    np = normalize_openalex_work(work)
    assert np.source == "openalex"
    assert np.source_id == "https://openalex.org/W123"
    assert np.doi == "10.1000/test.doi"                       # normalized from the URL form
    assert np.title == "Graph Retrieval Augmented Generation"
    assert np.abstract == "Graph retrieval uses citations"    # reconstructed
    assert np.publication_year == 2024
    assert np.venue_name == "Test Conference"
    assert np.pdf_url == "https://example.com/paper.pdf"
    assert np.reference_source_ids == [
        "https://openalex.org/WREF1",
        "https://openalex.org/WREF2",
    ]
    assert [a.name for a in np.authors] == ["Ada Lovelace"]
    assert {c.name for c in np.concepts} == {"Knowledge graphs", "Information retrieval"}
```

Test walkthrough:

- DOI tests protect dedup correctness.
- Title normalization protects the last-resort title+year match path.
- Abstract reconstruction catches the OpenAlex inverted-index shape.
- Fixture normalization proves the DTO mapping works without hitting OpenAlex.

## `backend/app/tests/test_bibtex.py`

```python
from app.ingestion.bibtex import (
    BibtexPaper,
    generate_bibtex_key,
    generate_fallback_bibtex,
    rekey_bibtex,
)


def _paper(**overrides) -> BibtexPaper:
    base = dict(
        title="P&L of Q&A systems: 100% _better_",
        publication_year=2024,
        venue_name="Conf & Journal",
        doi="10.1000/foo_bar",
        url=None,
        authors=["Ada Lovelace"],
    )
    base.update(overrides)
    return BibtexPaper(**base)


def test_key_format_and_collisions():
    paper = _paper()
    # first alphanumeric token of the title is "P" -> "p"
    assert generate_bibtex_key(paper, set()) == "lovelace2024p"
    assert generate_bibtex_key(paper, {"lovelace2024p"}) == "lovelace2024pa"
    assert generate_bibtex_key(paper, {"lovelace2024p", "lovelace2024pa"}) == "lovelace2024pb"


def test_key_handles_missing_fields():
    paper = _paper(title=None, publication_year=None, authors=[])
    assert generate_bibtex_key(paper, set()) == "unknownndpaper"


def test_escapes_hostile_title():
    paper = _paper()
    key = generate_bibtex_key(paper, set())
    bibtex = generate_fallback_bibtex(key, paper)
    assert r"\&" in bibtex
    assert r"\%" in bibtex
    assert r"\_" in bibtex
    assert "&" not in bibtex.replace(r"\&", "")   # no unescaped ampersand survives
    assert bibtex.startswith(f"@article{{{key},")


def test_rekey_bibtex_swaps_only_the_key():
    entry = "@article{Whatever_2020,\n  title = {Something},\n}\n"
    rekeyed = rekey_bibtex(entry, "lewis2020retrieval")
    assert rekeyed.startswith("@article{lewis2020retrieval,")
    assert "title = {Something}" in rekeyed
```

Test walkthrough:

- Key tests protect stable `\cite{...}` key generation.
- Collision tests protect projects with multiple papers that would otherwise share a key.
- Hostile-title escaping catches LaTeX-breaking characters before compile time.
- `rekey_bibtex()` ensures Crossref-provided entries use the project key.

## `backend/app/tests/test_fusion.py`

```python
from uuid import UUID, uuid4

from app.retrieval.fusion import rrf_fuse


def test_rrf_rewards_consensus_over_single_top_rank():
    a, b, c = uuid4(), uuid4(), uuid4()
    # a: rank2 + rank2 + rank1 across three lists; b: single rank1
    fused = rrf_fuse({"one": [b, a], "two": [c, a], "three": [a]}, k=60)
    assert fused[0].paper_id == a
    assert set(fused[0].retrieval_sources) == {"one", "two", "three"}


def test_rrf_empty_input():
    assert rrf_fuse({}) == []
    assert rrf_fuse({"empty": []}) == []


def test_rrf_dedupes_within_one_list():
    a = uuid4()
    fused = rrf_fuse({"one": [a, a, a]}, k=60)
    assert len(fused) == 1
    assert abs(fused[0].score - 1.0 / 61) < 1e-12   # counted once, at rank 1


def test_rrf_tie_order_is_deterministic():
    a = UUID("00000000-0000-0000-0000-00000000000a")
    b = UUID("00000000-0000-0000-0000-00000000000b")
    first = rrf_fuse({"one": [a], "two": [b]})
    second = rrf_fuse({"two": [b], "one": [a]})   # same input, different dict order
    assert [c.paper_id for c in first] == [c.paper_id for c in second] == [a, b]
```

Test walkthrough:

- Consensus test proves the whole reason to use RRF.
- Empty input test keeps retrieval safe when vector/graph return nothing.
- Dedup test prevents one signal from inflating a paper by repeating it.
- Tie-order test makes retrieval tests deterministic.

## `backend/app/tests/test_hybrid_retrieval.py`

Fakes for embeddings/vector/graph; a real session only for hydration. If `HybridRetriever` were hard to fake like this, it would be too coupled — that's the design point.

```python
from uuid import uuid4

from app.db.models import Paper
from app.graph.queries import GraphCandidate
from app.retrieval.embeddings import FakeEmbeddingClient
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector_search import VectorHit


class FakeVectorStore:
    def __init__(self, hits: list[VectorHit]):
        self.hits = hits

    async def search(self, query_embedding, limit=30):
        return self.hits


class FakeGraphSearch:
    def __init__(self, co_citation: list[GraphCandidate]):
        self._co_citation = co_citation

    async def bibliographic_coupling(self, seeds, limit=20):
        return []

    async def co_citation(self, seeds, limit=20):
        return self._co_citation

    async def shared_concepts(self, seeds, limit=20):
        return []

    async def direct_neighbors(self, seeds, limit=20):
        return []


async def test_hybrid_includes_vector_and_graph_candidates(db_session):
    vector_paper = Paper(title="Vector Paper", is_stub=False, cited_by_count=10)
    graph_paper = Paper(title="Graph Paper", is_stub=False, cited_by_count=99)
    db_session.add_all([vector_paper, graph_paper])
    await db_session.commit()

    hit = VectorHit(
        chunk_id=uuid4(),
        paper_id=vector_paper.id,
        text="supporting chunk text",
        section="title_abstract",
        title="Vector Paper",
        publication_year=2024,
        cited_by_count=10,
        is_stub=False,
        similarity=0.93,
    )
    retriever = HybridRetriever(
        embeddings=FakeEmbeddingClient(dim=8),
        vector_store=FakeVectorStore([hit]),
        graph=FakeGraphSearch(
            [
                GraphCandidate(
                    paper_id=str(graph_paper.id),
                    score=7.0,
                    signal="co_citation",
                    features={"co_citation_count": 7},
                )
            ]
        ),
        session=db_session,
    )

    results = await retriever.retrieve(project_id=uuid4(), query="graph retrieval", limit=10)
    by_id = {r.paper_id: r for r in results}

    assert vector_paper.id in by_id, "vector-only candidate must appear"
    assert graph_paper.id in by_id, "graph-only candidate must appear"
    assert by_id[vector_paper.id].retrieval_sources == ["vector"]
    assert by_id[graph_paper.id].retrieval_sources == ["co_citation"]
    assert by_id[vector_paper.id].text == "supporting chunk text"
    assert "co-cited" in by_id[graph_paper.id].reason
    assert all(r.reason for r in results)
```

Test walkthrough:

- Fake components keep the test focused on orchestration, not providers/databases.
- Vector-only candidate proves semantic retrieval contributes.
- Graph-only candidate proves structural retrieval contributes.
- Reason assertions prove the result is explainable, not just scored.

## `backend/app/tests/test_latex_patcher.py`

The load-bearing assertion: **failures leave no trace** — content, version, and `file_versions` all untouched.

```python
import pytest
from sqlalchemy import func, select

from app.db.models import FileVersion, ProjectFile
from app.latex.patcher import (
    InsertAfterPatch,
    PatchError,
    ReplaceTextPatch,
    apply_patch,
    preview_patch,
)

CONTENT = "\\section{Intro}\nStart writing here.\n\\section{Methods}\nTBD.\n"


@pytest.fixture
async def tex_file(db_session, project) -> ProjectFile:
    file = ProjectFile(project_id=project.id, path="main.tex", content=CONTENT, version=1)
    db_session.add(file)
    await db_session.commit()
    return file


async def _snapshot_count(db_session, file) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(FileVersion).where(FileVersion.file_id == file.id)
        )
    ).scalar_one()


async def test_replace_success_bumps_version_and_snapshots(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="Start writing here.", new_text="A brand new intro.",
    )
    result = await apply_patch(db_session, tex_file.project_id, patch)
    assert result == {"status": "applied", "path": "main.tex", "new_version": 2}
    await db_session.refresh(tex_file)
    assert "A brand new intro." in tex_file.content
    assert tex_file.version == 2
    snapshot = (
        await db_session.execute(
            select(FileVersion).where(FileVersion.file_id == tex_file.id, FileVersion.version == 2)
        )
    ).scalar_one()
    assert snapshot.created_by == "agent"


async def test_insert_after_success(db_session, tex_file):
    patch = InsertAfterPatch(
        operation="insert_after", path="main.tex", base_version=1,
        anchor_text="\\section{Intro}", new_text="\n\\label{sec:intro}",
    )
    await apply_patch(db_session, tex_file.project_id, patch)
    await db_session.refresh(tex_file)
    assert "\\section{Intro}\n\\label{sec:intro}" in tex_file.content


async def test_stale_version_rejected_without_mutation(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=99,
        old_text="Start writing here.", new_text="nope",
    )
    with pytest.raises(PatchError) as err:
        await apply_patch(db_session, tex_file.project_id, patch)
    assert err.value.code == "stale_version"
    assert err.value.details["current_version"] == 1
    await db_session.refresh(tex_file)
    assert tex_file.content == CONTENT and tex_file.version == 1
    assert await _snapshot_count(db_session, tex_file) == 0


async def test_anchor_not_found(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="THIS TEXT DOES NOT EXIST", new_text="x",
    )
    with pytest.raises(PatchError) as err:
        await apply_patch(db_session, tex_file.project_id, patch)
    assert err.value.code == "anchor_not_found"
    await db_session.refresh(tex_file)
    assert tex_file.content == CONTENT


async def test_anchor_ambiguous_reports_count(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="\\section", new_text="\\subsection",   # occurs twice
    )
    with pytest.raises(PatchError) as err:
        await apply_patch(db_session, tex_file.project_id, patch)
    assert err.value.code == "anchor_ambiguous"
    assert err.value.details["occurrences"] == 2


async def test_multiline_anchor(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="Start writing here.\n\\section{Methods}",
        new_text="Rewritten.\n\\section{Methods}",
    )
    result = await apply_patch(db_session, tex_file.project_id, patch)
    assert result["new_version"] == 2


async def test_preview_does_not_apply(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="Start writing here.", new_text="Previewed.",
    )
    preview = await preview_patch(db_session, tex_file.project_id, patch)
    assert "Previewed." in preview["after"]
    assert preview["before"] == CONTENT
    await db_session.refresh(tex_file)
    assert tex_file.content == CONTENT and tex_file.version == 1
```

Patcher test walkthrough:

- Success tests prove content changes, version bump, and snapshots happen together.
- Failure tests prove stale/ambiguous/missing anchors do not mutate content.
- Multiline anchor test matches real LaTeX patch behavior.
- Preview test proves UI patch proposals are non-mutating.

## `backend/app/tests/test_path_sanitizer.py`

```python
import pytest

from app.latex.sanitizer import UnsafePathError, sanitize_project_path


@pytest.mark.parametrize("path", ["main.tex", "sections/intro.tex", "figures/plot-1.pdf"])
def test_safe_paths(path):
    assert sanitize_project_path(path) == path


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../x", "a/../b", ".env", "a/.hidden/b.tex", "a\\.tex", "a b.tex", "a\x00b", ""],
)
def test_unsafe_paths(path):
    with pytest.raises(UnsafePathError):
        sanitize_project_path(path)
```

Sanitizer test walkthrough:

- Safe paths are the ordinary project file paths the app should allow.
- Unsafe paths cover absolute paths, traversal, hidden files, backslashes, spaces, null bytes, and empty input.
- These tests protect every file/compile/patch entrypoint that accepts a path.

## `backend/app/tests/test_agent_stream.py`

The single highest-value test in the repo: drives the orchestrator with a scripted `FakeLLMClient` and asserts the exact event sequence, persistence, and the errors-are-data property.

```python
from pydantic import BaseModel
from sqlalchemy import select

from app.agent.llm.base import LLMResponse, ToolCall
from app.agent.llm.fake import FakeLLMClient
from app.agent.orchestrator import AgentTurnContext, run_agent_turn
from app.agent.schemas import ToolError
from app.db.models import AgentMessage, AgentSession, ToolCallRecord


class EchoOutput(BaseModel):
    ok: bool = True
    summary: str = "echo done"


class FakeRegistry:
    def specs(self):
        return []

    async def execute(self, name, arguments):
        return EchoOutput(summary=f"{name} executed")


class FailingRegistry(FakeRegistry):
    async def execute(self, name, arguments):
        raise ToolError("anchor_ambiguous", "anchor occurs 3 times; use a longer anchor")


async def _agent_session(db_session, project) -> AgentSession:
    session_row = AgentSession(project_id=project.id, user_id=project.user_id, title="test")
    db_session.add(session_row)
    await db_session.commit()
    return session_row


async def test_agent_stream_event_sequence(db_session, project):
    agent_session = await _agent_session(db_session, project)
    llm = FakeLLMClient(
        [
            LLMResponse(
                text="Inspecting the project.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="inspect_latex_project",
                        arguments={"project_id": str(project.id)},
                    )
                ],
            ),
            LLMResponse(text="Here are my suggestions."),
        ]
    )
    events: list[tuple[str, dict]] = []

    async def emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    turn = AgentTurnContext(project_id=project.id, project_name=project.name)
    await run_agent_turn(
        db_session, agent_session.id, "suggest citations", turn, FakeRegistry(), llm, emit
    )

    assert [n for n, _ in events] == [
        "message_delta", "tool_call", "tool_result", "message_delta", "done",
    ]

    records = (
        await db_session.execute(
            select(ToolCallRecord).where(ToolCallRecord.session_id == agent_session.id)
        )
    ).scalars().all()
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].tool_name == "inspect_latex_project"

    roles = [
        m.role
        for m in (
            await db_session.execute(
                select(AgentMessage)
                .where(AgentMessage.session_id == agent_session.id)
                .order_by(AgentMessage.created_at)
            )
        ).scalars()
    ]
    assert roles == ["user", "assistant"]


async def test_tool_error_flows_back_into_conversation(db_session, project):
    agent_session = await _agent_session(db_session, project)
    llm = FakeLLMClient(
        [
            LLMResponse(
                text="",
                tool_calls=[ToolCall(id="c1", name="inspect_latex_project", arguments={})],
            ),
            LLMResponse(text="I hit an error and adjusted."),
        ]
    )
    events: list[tuple[str, dict]] = []

    async def emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    turn = AgentTurnContext(project_id=project.id, project_name=project.name)
    await run_agent_turn(
        db_session, agent_session.id, "edit the intro", turn, FailingRegistry(), llm, emit
    )

    tool_results = [p for n, p in events if n == "tool_result"]
    assert tool_results[0]["error"] == "anchor_ambiguous"

    # errors are data: the SECOND llm call must contain the error as a tool message
    second_call_messages = llm.calls[1]
    tool_messages = [m for m in second_call_messages if m.role == "tool"]
    assert tool_messages and "anchor_ambiguous" in tool_messages[0].content
```

Agent-stream test walkthrough:

- The event-order test proves the UI can render progress as tools run.
- Tool-call persistence proves observability is durable.
- Message persistence proves conversation state is saved.
- The error-flow test proves failed tools are fed back to the model as data.
- `FakeLLMClient` makes all of this testable without provider calls.

## Fixtures

### `backend/app/tests/fixtures/openalex_work.json`

```json
{
  "id": "https://openalex.org/W123",
  "doi": "https://doi.org/10.1000/Test.DOI",
  "display_name": "Graph Retrieval Augmented Generation",
  "publication_year": 2024,
  "publication_date": "2024-01-15",
  "cited_by_count": 42,
  "abstract_inverted_index": {
    "Graph": [0],
    "retrieval": [1],
    "uses": [2],
    "citations": [3]
  },
  "referenced_works": [
    "https://openalex.org/WREF1",
    "https://openalex.org/WREF2"
  ],
  "authorships": [
    {
      "author_position": "first",
      "author": {
        "id": "https://openalex.org/A1",
        "display_name": "Ada Lovelace"
      }
    }
  ],
  "concepts": [
    { "display_name": "Knowledge graphs", "score": 0.9 },
    { "display_name": "Information retrieval", "score": 0.8 }
  ],
  "primary_location": {
    "source": { "display_name": "Test Conference" }
  },
  "open_access": {
    "oa_url": "https://example.com/paper.pdf"
  }
}
```

Fixture walkthrough:

- `openalex_work.json`: full detail response for normalization/import tests.
- `openalex_search.json`: search response shape for paper search tests.
- `crossref_bibtex.txt`: publisher-style BibTeX for re-keying tests.
- `semantic_scholar_paper.json`: optional enrichment fixture for future tests.
- Fixtures are intentionally tiny but include the weird fields that matter: DOI URL, inverted abstract, references, authorships, concepts.

### `backend/app/tests/fixtures/openalex_search.json`

```json
{
  "results": [
    {
      "id": "https://openalex.org/W123",
      "doi": "https://doi.org/10.1000/Test.DOI",
      "display_name": "Graph Retrieval Augmented Generation",
      "publication_year": 2024,
      "cited_by_count": 42,
      "authorships": [
        { "author": { "id": "https://openalex.org/A1", "display_name": "Ada Lovelace" } }
      ],
      "primary_location": { "source": { "display_name": "Test Conference" } }
    },
    {
      "id": "https://openalex.org/W456",
      "doi": null,
      "display_name": "Citation Networks for Retrieval",
      "publication_year": 2023,
      "cited_by_count": 17,
      "authorships": [
        { "author": { "id": "https://openalex.org/A2", "display_name": "Alan Turing" } }
      ],
      "primary_location": { "source": { "display_name": "Journal of Testing" } }
    }
  ]
}
```

### `backend/app/tests/fixtures/crossref_bibtex.txt`

```text
@article{Lewis_2020,
  title = {Retrieval-Augmented Generation for Knowledge-Intensive {NLP} Tasks},
  author = {Lewis, Patrick and Perez, Ethan and Piktus, Aleksandra},
  journal = {Advances in Neural Information Processing Systems},
  year = {2020},
  doi = {10.1000/test.doi}
}
```

### `backend/app/tests/fixtures/semantic_scholar_paper.json`

```json
{
  "paperId": "S2123",
  "title": "Graph Retrieval Augmented Generation",
  "abstract": "Graph retrieval uses citations",
  "year": 2024,
  "venue": "Test Conference",
  "citationCount": 42,
  "fieldsOfStudy": ["Computer Science"],
  "tldr": { "text": "Uses citation graphs to improve retrieval." }
}
```

## Running

```bash
# everything (inside the container, against compose services)
make test-backend

# pure unit tests only (no containers needed)
cd backend && pytest app/tests/test_normalize.py app/tests/test_bibtex.py \
  app/tests/test_fusion.py app/tests/test_path_sanitizer.py
```

The acceptance rule for the whole project: every ⭐ core file has a test that fails before you implement it and passes after. That's how the build stays fast without becoming a black box.

Testing philosophy recap:

- Unit tests protect pure logic you will hand-write.
- Integration tests protect app wiring and database behavior.
- Fakes replace LLMs/embeddings wherever possible.
- JSON fixtures replace external scholarly APIs.
- Tests should fail loudly when an architectural invariant is broken: dedup, stubs, exact anchors, bounded tool loop, and RRF consensus.
