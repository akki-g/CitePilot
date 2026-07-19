# Guide 10: Showcase Readiness

**Audience:** an agent (or human) picking this repo up to take it from "code complete" to "demo on a projector." Work through the tasks in order — each one has acceptance checks. Do not skip Task 0; every later task assumes its state.

---

## Task 0 — Understand the current state (read, don't build yet)

What is already done:

- **Backend (guides 01–08) is implemented and has been through a review pass.** Every module was checked against its guide; ~25 bugs were fixed directly in the code (fix sites are marked with `# fix:` comments) and each guide ends with a "Changes (review pass, 2026-07-05)" section describing what was wrong. All backend entry points import cleanly: `app.main`, `app.workers.arq_app`, `app.workers.jobs`, `app.mcp_server.server`, `app.graph.resync`.
- **The frontend was rewritten from Next.js to Vite + React 19 + TypeScript** (`apps/web`). It has been reviewed: `pnpm build` (tsc + vite) and `pnpm lint` both pass clean. It covers the full demo surface: project list/create, CodeMirror editor with versioned saves, paper search/import with job polling, bibliography panel, XYFlow citation graph with "enrich" button, SSE agent panel (tool trace, citation suggestion cards, patch review/accept), and PDF compile/preview.
- **Infra is in place:** `docker-compose.yml` runs postgres (pgvector), neo4j, redis, backend, worker (with Tectonic pre-warmed), and web. The Makefile has `up`, `migrate`, `test-backend`, `resync-graph` targets. Alembic migration `0001_initial_schema.py` exists.

What is NOT done (that's this guide):

1. Guide 09 (tests + fixtures) was never implemented — `backend/app/tests/` contains only `__init__.py`.
2. There is no `.env` (only `.env.example`), so nothing can boot.
3. Docker images have never been built with the current `pyproject.toml` (the `mcp` dependency was added during review — a rebuild is mandatory, not optional, because Python deps install at image build time even though source is volume-mounted).
4. The system has never been run end-to-end.
5. No demo data, no demo script, no root README.

---

## Task 1 — Implement the test suite (guide 09)

Type in every file from `guides/backend-modules/09-tests-and-fixtures.md` exactly as written:

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

Notes for whoever types these:

- The backend code was fixed during review, so if a test contradicts current code, trust the test + the guide's Changes section — they agree. In particular: `RetrievalResult` has a `chunk_id` field (not `chunk`), `InsertAfterPatch` has `base_version`, and the patcher error code is `file_not_found`.
- Pure unit tests (`test_normalize`, `test_bibtex`, `test_fusion`, `test_path_sanitizer`) can run on the host if a venv exists; the DB-backed ones (`test_latex_patcher`, `test_hybrid_retrieval`, `test_agent_stream`, `test_health`) must run inside the backend container against the compose services, **after Task 3's migration step**.
- `APP_ENV=test` makes `create_llm_client` and `create_embedding_client` return fakes — no test may hit a real external API.

**Acceptance:** `make test-backend` (i.e. `docker compose exec backend pytest`) is green. Run it after Task 3; run the pure-unit subset earlier if you want fast feedback.

---

## Task 2 — Create the real `.env`

```bash
cp .env.example .env
```

Then edit these values (everything else can keep its default):

| Variable | Value | Why |
|---|---|---|
| `OPENALEX_MAILTO` | a real email address | **Hard requirement.** `OpenAlexClient` raises at construction without it; paper search/import will 500. |
| `CROSSREF_MAILTO` | same email | Polite-pool etiquette for BibTeX content negotiation. |
| `LLM_PROVIDER` | `anthropic` | Already the default. |
| `LLM_MODEL` | `claude-sonnet-4-6` | Good speed/quality balance for a live agent demo. |
| `LLM_API_KEY` | real Anthropic key | Agent panel is dead without it. |
| `EMBEDDING_PROVIDER` | `openai` | Already the default. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 1536 dimensions — **must** match `EMBEDDING_DIM=1536` and the `vector(1536)` column. Do not use a different-dimension model without a migration. |
| `EMBEDDING_API_KEY` | real OpenAI key | Otherwise chunks never get vectors and retrieval returns nothing. |

Frontend note: the web app reads `VITE_API_BASE_URL` and falls back to `http://localhost:8000`, which is correct for local compose (the browser talks to the published backend port). Nothing to set unless the demo machine serves the API elsewhere.

**Acceptance:** `.env` exists, is gitignored (check `git status` — it must not appear), and contains no placeholder values in the rows above.

---

## Task 3 — Build, boot, migrate, verify startup

```bash
make up          # docker compose up --build  (first build downloads Tectonic + warms its bundle; expect several minutes)
```

In a second terminal, once containers are up:

```bash
make migrate     # docker compose exec backend alembic upgrade head
```

Then verify, in order:

1. `curl http://localhost:8000/api/health` → `{"status":"ok","postgres":"ok","neo4j":"ok","redis":"ok"}`.
2. Backend logs show one JSON `app.startup` line and **no** `db.embedding_dim_check_skipped` warning after the migration ran (restart the backend once post-migration if you saw it: `docker compose restart backend`).
3. Neo4j browser at `http://localhost:7474` (neo4j / citepilot-password): `SHOW CONSTRAINTS` lists the four constraints from guide 02.
4. Worker logs show arq started with 4 registered functions (`ingest_paper_job`, `expand_citation_graph_job`, `embed_chunks_job`, `compile_latex_job`).
5. `http://localhost:3000` renders the project list page with all four status pills green.

Common failures at this step:

- **`ModuleNotFoundError: No module named 'mcp'`** → the image predates the review-pass `pyproject.toml`; rebuild (`docker compose build backend worker`).
- **Health shows `postgres: error`** right after boot → healthchecks should prevent this, but if Postgres restarted, `pool_pre_ping` self-heals; re-curl.
- **Embedding-dim RuntimeError at startup** → someone changed `EMBEDDING_DIM` or the model; revert to 1536/`text-embedding-3-small`.

**Acceptance:** all five checks above pass, and now `make test-backend` (from Task 1) is green.

---

## Task 4 — End-to-end feature verification

Walk the entire demo path once, fixing anything that breaks. Do this in the browser at `http://localhost:3000`:

1. **Create a project** → lands in the workspace with `main.tex` (v1) and `references.bib` (v1) in the file tree.
2. **Editor + versioning** → edit `main.tex`, Save → version badge bumps to v2, "Saved" flash appears. (409 conflict path: only triggerable via concurrent edits — skip unless curious.)
3. **Import papers** (left panel search). Use OpenAlex source. Import these five so the graph signals actually fire (they cite each other heavily):
   - "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (Lewis et al., 2020)
   - "Dense Passage Retrieval for Open-Domain Question Answering"
   - "REALM: Retrieval-Augmented Language Model Pre-Training"
   - "Atlas: Few-shot Learning with Retrieval Augmented Language Models"
   - "From Local to Global: A Graph RAG Approach to Query-Focused Summarization"
   Each import shows a job row going `queued → running → completed` (~2–5 s each with warm Redis cache; first hit is network-bound). The bibliography panel fills in with bibtex keys.
4. **Verify ingestion side effects** (terminal):
   ```bash
   docker compose exec postgres psql -U citepilot -c "SELECT count(*) FILTER (WHERE is_stub) AS stubs, count(*) AS total FROM papers;"
   docker compose exec postgres psql -U citepilot -c "SELECT count(*) FROM paper_chunks WHERE embedding IS NOT NULL;"
   ```
   Expect: hundreds of stubs, and embedded-chunk count ≥ number of imported (non-stub) papers. If embeddings stay NULL, check worker logs for `embed.failed` (bad `EMBEDDING_API_KEY` is the usual cause).
5. **Citation graph panel** → select an imported paper in the bibliography → nodes + edges render; stub nodes are dashed amber. Click the ⟳ "enrich" button → job promotes top stubs → within ~10 s the bibliography/graph densify.
6. **Agent panel** → select a sentence in the editor, ask "What related work should I cite here?" → tool trace streams (`retrieve_evidence` / `rank_related_work`), citation suggestion cards appear with graph-grounded reasons ("shares N references…", "co-cited with…"), "Insert citation" drops `\cite{key}` into the draft.
7. **Patch proposal** → ask the agent "Add a Related Work section summarizing these papers." → a patch proposal card appears (the agent's `patch_latex_file` is intercepted, not applied) → Accept → file version bumps and content updates.
8. **Compile** → PDF preview panel → Compile → status `queued → running → completed` → PDF renders in the iframe. Break `main.tex` (`\begin{documnet}`), recompile → status `failed` with a useful log tail; fix and recompile.
9. **MCP (optional, but a strong showcase moment):**
   ```bash
   npx @modelcontextprotocol/inspector docker compose exec -T backend python -m app.mcp_server.server
   ```
   Inspector lists 10 tools; `search_papers` works; the call appears in `tool_calls` with `session_id IS NULL`.

**Acceptance:** every numbered step behaves as described. Anything that doesn't is a bug to fix before moving on — the backend Changes sections in `guides/backend-modules/0*.md` are the reference for intended behavior.

---

## Task 5 — Seed the demo project + write the demo script

Do not demo on an empty database. Prepare:

1. A project named something credible (e.g. "GraphRAG Survey — Related Work") with the five papers from Task 4 already imported, graph enriched once, and one successful compile so the PDF preview isn't blank.
2. A paragraph already in `main.tex` about retrieval-augmented generation that the presenter can select for the citation-suggestion moment.
3. Write `guides/DEMO_SCRIPT.md` — the 5-minute walkthrough, in this order (it tells the product story from strongest hook to deepest tech):
   1. Open workspace: "Overleaf-style editor, but citation-aware." (10 s)
   2. Select the prepared paragraph → agent → citation suggestions with *reasons* — emphasize the reasons are computed from graph features, never LLM-generated. (90 s)
   3. Insert a citation → `suggest_bibtex` via agent or show `references.bib` → Compile → PDF. (60 s)
   4. Citation graph panel → click through neighborhood → hit Enrich and watch stubs promote live. (60 s)
   5. The architecture slide-in-words: Postgres is truth, Neo4j is a derived mirror (`make resync-graph` proves it), five ranked lists fused with RRF, bounded agent loop, anchor-based patches with human approval. (60 s)
   6. If the audience is technical: MCP Inspector showing the same ten tools exposed to any MCP client. (30 s)
4. Add a short **root `README.md`**: one-paragraph pitch, architecture diagram or bullet stack, `make up` + `make migrate` quickstart, link to `guides/` and the demo script. The repo currently has no root README and a showcase repo needs one.

**Acceptance:** a cold `make up` on the demo machine, followed by opening the seeded project, reaches the citation-suggestion moment in under 60 seconds of clicking.

---

## Task 6 — Final hardening sweep (small, do last)

- `cd apps/web && pnpm build && pnpm lint` — keep clean. The build currently warns about a ~900 kB chunk; acceptable for a demo. If you have spare time, lazy-load `CitationGraph` (XYFlow) and `LatexEditor` (CodeMirror) with `React.lazy` — they're the bulk of it. Do not do this at the cost of demo stability.
- `make test-backend` — green.
- `git status` — no stray untracked junk (`dist/`, `tsconfig.tsbuildinfo`, `citenv/` are already gitignored), and **commit the new frontend source dirs** (`apps/web/src/components|lib|pages|stores`) plus the backend alembic files, which are currently untracked. Heads-up: the root `.gitignore` deliberately excludes `guides/` and all `*.md` except `README.md` — the guides (including this one and `DEMO_SCRIPT.md`) are local working docs and will never appear in `git status`. That is intentional; the root README from Task 5 is the only markdown that ships.
- Demo-day resilience: OpenAlex responses are Redis-cached (searches 24 h, works 7 d) — run the full demo flow once on the demo network so every external call the script needs is warm. The LLM call is the only live network dependency during the demo; have one canned screenshot of the agent turn as a fallback.
- Restart everything once (`make down && make up`, **without** `-v` so volumes survive) and confirm the seeded project is intact — proves the demo survives a reboot.

Known accepted limitations (say them if asked, don't fix now): single dev user (no auth), one title+abstract chunk per paper (no full-text), non-streaming LLM tokens (turn-level streaming only), MCP is stdio-only by design.

---

## Order of operations, condensed

```
Task 1 (type tests)  →  Task 2 (.env)  →  Task 3 (build/migrate/verify, then run tests)
→  Task 4 (end-to-end walk, fix what breaks)  →  Task 5 (seed + demo script + README)
→  Task 6 (hardening sweep)
```
