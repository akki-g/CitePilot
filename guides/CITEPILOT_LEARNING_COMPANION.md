# CitePilot — Learning Companion & Interview Prep

This file is for **you**, not the coding agent. It explains the fundamentals behind each subsystem, why the guide makes the decisions it makes, which modules you should hand-write yourself to actually learn, and how to talk about all of it in an interview focused on knowledge graphs, GraphRAG, agentic systems, tool calling, and MCP.

---

## 1. What to Hand-Write vs. What to Delegate

Your stated plan: the agent builds everything, then you rewrite the parts worth learning. Here's the priority order — these six modules ARE the interview material; everything else is plumbing:

| Priority | Module | What it teaches |
|---|---|---|
| 1 | `retrieval/hybrid.py` + `fusion.py` | GraphRAG orchestration and rank fusion — the thesis of the project |
| 2 | `agent/orchestrator.py` | The agentic tool loop — how every modern agent actually works |
| 3 | `graph/queries.py` | Cypher, co-citation, bibliographic coupling — real KG query patterns |
| 4 | `mcp_server/` + `agent/tool_registry.py` | MCP and tool design — how capabilities are exposed to models |
| 5 | `ingestion/normalize.py` + `upsert.py` | Entity resolution — the unglamorous heart of every knowledge graph |
| 6 | `latex/patcher.py` | Safe agent write-actions — anchored edits, versioning, failure design |

Skip hand-writing entirely: all frontend, Docker/compose, Alembic boilerplate, CRUD routes, the Tectonic wrapper. Read them once; don't reproduce them.

A good rhythm: after the agent finishes a milestone, delete one of the modules above, rewrite it from the guide's spec until the tests pass, then diff against the agent's version. The tests were designed to make this possible (`test_fusion.py`, `test_latex_patcher.py`, `test_agent_stream.py` are executable specs).

---

## 2. Knowledge Graph Fundamentals (as built here)

### 2.1 What the graph actually is

A knowledge graph is typed entities + typed relationships, where the *relationships carry the signal*. CitePilot's schema:

```text
(:Paper)-[:CITES]->(:Paper)
(:Paper)-[:WRITTEN_BY]->(:Author)
(:Paper)-[:MENTIONS_CONCEPT]->(:Concept)
(:Paper)-[:PUBLISHED_IN]->(:Venue)
```

Three design decisions worth internalizing, because they generalize to any KG job:

**1. The graph is a derived store, not the source of truth.** Postgres owns every entity; Neo4j holds a rebuildable mirror (`resync_graph()` proves it). This is the standard production pattern — graph databases are excellent at traversal and terrible as systems of record. If asked "what if Neo4j dies?", your answer is "I rebuild it from Postgres in one command; I designed for that on day one."

**2. Entity resolution is the hard part.** The same paper arrives from OpenAlex, Semantic Scholar, and Crossref with different IDs. If you insert naively, one real-world paper becomes three nodes and its citation edges split across them — the graph silently becomes wrong. CitePilot's answer: normalize identifiers (DOIs are case-insensitive and arrive with/without URL prefixes), then match in a strict priority order (DOI → openalex_id → s2_id → title+year), and always *enrich the existing row* rather than insert. This is 80% of real-world KG engineering and interviewers know it.

**3. Incomplete graphs need placeholder nodes.** You import one paper; its 40 references aren't imported. Without those nodes you have zero citation edges and every graph query returns nothing. The **stub paper** pattern (a minimal node flagged `is_stub`, promoted in place when fully imported, keeping its ID and edges) is what makes the graph dense enough to be useful from the very first import. This is a genuinely good interview story because it's a failure you *predicted and designed around* rather than hit.

### 2.2 The two graph metrics that matter

Both are classic bibliometrics, and both are two-hop Cypher patterns:

- **Bibliographic coupling** — papers that cite many of the *same references* as your seed. Pattern: `(seed)-[:CITES]->(ref)<-[:CITES]-(other)`. Signal meaning: "these papers build on the same foundations" → strong for finding *contemporaries and competitors*.
- **Co-citation** — papers that are frequently *cited together with* your seed by third parties. Pattern: `(citer)-[:CITES]->(seed)` and `(citer)-[:CITES]->(other)`. Signal meaning: "the community treats these as related" → strong for finding *the canonical companions* of a paper.

Learn to draw both patterns on a whiteboard. They're the difference between "I used a graph database" and "I understand why the graph earns its place."

### 2.3 A Cypher trap you designed around

Undirected variable-length expansion with a bare LIMIT — `MATCH (seed)-[:CITES*1..2]-(n) ... LIMIT 50` — explodes on hub nodes (a survey cited 10,000 times) and truncates arbitrarily. The fix in the guide: expand *per direction* with a *per-hop* cap, ordered by a quality signal (`cited_by_count`) before limiting. General lesson: on real graphs, degree distributions are heavy-tailed; every traversal needs a budget.

---

## 3. GraphRAG Fundamentals

### 3.1 The one-sentence thesis

> Vector search answers "what text is similar?"; the graph answers "what is *structurally related*?" — and the papers you actually need to cite are frequently structurally related without being textually similar (different vocabulary, older terminology, foundational works).

That sentence is your interview opener. CitePilot exists to make it concrete.

### 3.2 The retrieval pipeline, conceptually

```text
query → embed → vector top-30 chunks ──→ ranked list #1 (semantic)
                     │
                     └→ top-5 papers become graph SEEDS
                           ├→ bibliographic coupling → ranked list #2
                           ├→ co-citation            → ranked list #3
                           ├→ shared concepts        → ranked list #4
                           └→ direct cite neighbors  → ranked list #5

all five lists → Reciprocal Rank Fusion → hydrate with evidence + reasons → top-k
```

The elegance: each signal is an independent, individually-debuggable ranked list. You can log each list, eyeball each list, and unit-test the fusion separately from the retrieval.

### 3.3 Why Reciprocal Rank Fusion (and why not a weighted score)

The naive approach — `0.5·similarity + 0.2·graph_relevance + 0.15·authority...` — fails because the terms live on incompatible scales (cosine ∈ [0,1], citation counts unbounded, path distance inverted) and the weights become an untestable guessing game.

RRF sidesteps scale entirely by using *ranks*:

```text
score(paper) = Σ over lists containing it:  1 / (k + rank_in_that_list)     (k = 60)
```

Properties worth being able to state precisely:

- **Scale-free**: only rank positions matter, so cosine similarity and co-citation counts fuse cleanly without normalization.
- **Consensus-rewarding**: a paper at rank 5 in three lists beats a paper at rank 1 in one list — appearing across independent signals is exactly what "relevant" means here.
- **One parameter**, k, which mostly controls how much the top of each list dominates; 60 is the literature-standard default and rarely worth tuning.
- **Upgrade path**: when you have relevance labels, the per-list features become inputs to a learned ranker. RRF is the correct zero-data starting point, and saying so signals engineering maturity ("I didn't hand-tune weights against vibes; I used a scale-free fusion and kept the features for a future learned ranker").

### 3.4 Explanations are a feature of retrieval, not decoration

Every result carries `retrieval_sources` (which lists it appeared in) and a generated reason ("one hop from Lewis 2020, co-cited by 7 papers, shares concepts {X, Y}"). Two reasons this matters: users don't trust citation recommendations they can't audit, and *you* can't debug a retrieval system whose outputs are bare floats. Grounding the reason strings in computed features (not LLM freeform) means they're never hallucinated.

### 3.5 Chunking lesson

The guide deliberately embeds **one chunk per paper (title + abstract)** and forbids synthetic "metadata summary" chunks. Why: template-generated text ("This paper covers concepts A, B, C...") is lexically similar to other template text, so those chunks cluster with each other and pollute top-k. And concept overlap is already a *graph* signal — encoding it in vector space double-counts it at fusion time. General principle: each signal should enter the ranker exactly once, through the modality where it's strongest.

---

## 4. Agentic Systems & Tool Calling Fundamentals

### 4.1 The anatomy of every agent

Strip away the branding and every production agent is this loop:

```text
messages = [system_prompt, context, user_message]
loop (bounded):
    response = LLM(messages, tool_specs)
    stream any text to the user
    if no tool calls: break
    for each tool call:
        validate args → execute → log → append result (or ERROR) to messages
```

The properties that make it production-grade rather than a demo, all present in `orchestrator.py`:

1. **Bounded iterations** (MAX = 8) — agents must not be able to loop forever.
2. **Errors are data**: a failed tool call returns a structured error *into the conversation*, and the model retries with corrected arguments. `anchor_ambiguous: found 3 matches` → the model sends a longer anchor. Self-correction is not magic; it's error messages designed for a model reader.
3. **Everything is observable**: every call persists to `tool_calls` and streams to the UI trace. If you can't replay what the agent did, you can't debug it.
4. **No hidden routing**: the guide deliberately has *no intent classifier*. Tool selection **is** intent classification — a model given well-described tools routes itself, with one less LLM hop and one less failure mode. Be ready to defend this: "I considered an explicit intent router and cut it; the tool-calling model already routes implicitly, and the classifier would add latency plus a new misclassification failure mode without adding capability."

### 4.2 Tool design principles (the interview meat)

- **Narrow and typed.** `retrieve_evidence(project_id, query, limit)` — not `run_sql(query)`. Every input/output is a Pydantic model; the JSON schema shown to the model is generated from it, so validation and documentation can't drift apart.
- **Descriptions are prompts.** The model chooses tools by reading their descriptions. A vague description is a routing bug.
- **Design for the model's weaknesses.** The best example in the project: LaTeX patches are *anchor-based* (`old_text` must appear exactly once) rather than offset-based, because LLMs cannot count characters reliably. Offset bugs corrupt silently; anchor bugs fail loudly with a retryable error. When an interviewer asks "how do you make agent write-actions safe?", this is your answer: choose representations that convert silent corruption into loud, recoverable failure — plus versioning (stale-version rejection) and human-in-the-loop acceptance for UI-originated patches.
- **Bound the blast radius.** No SQL/Cypher/shell tools; project-scoped everything; results truncated before storage; compile sandboxed with no network and a timeout.

### 4.3 Streaming

Users won't wait 20 seconds staring at a spinner while five tools run. The event protocol (`message_delta`, `tool_call`, `tool_result`, `citation_suggestions`, `patch_proposal`, `done`) turns latency into visible progress. Implementation gotcha worth knowing cold: browser `EventSource` can't send POST bodies, so SSE-over-POST is consumed with `fetch()` + ReadableStream. This tiny fact separates people who've built streaming agents from people who've read about them.

---

## 5. MCP Fundamentals

### 5.1 What MCP is, in one paragraph

The Model Context Protocol is a standard for exposing tools (and resources/prompts) to AI clients over a defined transport — so a capability is written once and usable from Claude Desktop, Cursor, an IDE, or a custom runtime, instead of being welded to one app's agent loop. Think "USB for model capabilities": the server declares typed tools; any compliant client can discover and call them.

### 5.2 The architectural point CitePilot makes

The same ten tools power both the in-app agent and the MCP server, through one registry, with **zero duplicated logic** — MCP tools are docstring-carrying wrappers around `agent/tools.py`. That's the design lesson: *capabilities are a layer; agents and protocols are consumers of that layer.* When you demo `retrieve_evidence` from Claude Desktop against the same knowledge graph your web app uses, the point makes itself.

### 5.3 Transports and the security cliff

- **stdio**: client launches the server as a subprocess; inherently local; what CitePilot ships.
- **Streamable HTTP**: network-exposed; the moment you cross this line the server needs real authentication, because an MCP server typically has privileged data access (CitePilot's touches the whole database). Knowing that stdio→HTTP is a security boundary, not just a config change, is exactly the kind of detail that lands in interviews.

### 5.4 MCP tool-description discipline

MCP clients show your docstrings to the model verbatim — the docstring *is* the interface. Write them for a model reader: what the tool does, what the inputs mean, what comes back, when to use it. Vague docstrings produce agents that never call your tool or call it wrong.

---

## 6. System Design Talking Points (Q&A prep)

**"Walk me through the architecture."**
> Next.js/TypeScript workspace in front; FastAPI backend; Postgres+pgvector as the durable store and vector index; Neo4j as a rebuildable graph mirror for traversal; Redis for the async job queue (arq) and external-API cache; Tectonic in a sandboxed worker for LaTeX. The agent is a bounded tool loop over ten typed tools, and the identical tools are exposed through an MCP server via one shared registry.

**"Why both Postgres and Neo4j? Isn't that overkill?"**
> Postgres is the source of truth and does vectors-next-to-metadata well; Neo4j makes multi-hop relationship queries — co-citation, bibliographic coupling, neighborhood expansion — trivial to express and fast to run. I kept the coupling honest: Neo4j is fully derived, and `resync_graph` rebuilds it from Postgres in one command. I *could* do two-hop queries with recursive CTEs in Postgres, and for a smaller scope I would — but relationship-heavy retrieval is the product, so the graph store earns its complexity.

**"Why not just a vector database?"**
> Vector search finds textually similar chunks; it misses structural relevance. A foundational paper uses 2015 vocabulary for a 2025 paragraph — low cosine similarity, mandatory citation. Citation edges, co-citation, and bibliographic coupling recover exactly those. The hybrid fuses five independent ranked lists with RRF, so a paper that's both semantically close and structurally central rises to the top.

**"How do you combine the signals?"**
> Reciprocal Rank Fusion — rank-based, so incompatible scales fuse without normalization, and consensus across independent signals is rewarded. One parameter, standard default. Hand-tuned weighted sums over raw scores are untestable guesswork; RRF is the correct zero-training-data baseline, and the per-candidate features are retained for a future learned ranker.

**"What was the hardest problem?"**
> Two candidates. Data-side: entity resolution and graph completeness — dedup across three metadata sources so one paper never becomes two nodes, and stub papers so citation edges exist before their endpoints are fully imported; without stubs every graph query returns nothing. Agent-side: making write-actions safe — anchor-based patches instead of character offsets, because models can't count characters and offset bugs corrupt files silently, whereas anchor mismatches fail loudly and the loop retries.

**"How do you evaluate retrieval quality?"** *(they will ask; be honest and concrete)*
> MVP is qualitative — reason strings and per-list logging make results auditable. The designed next step is a harness that replays real papers' related-work sections as queries: hold out a paper's actual citations, run the retriever on each paragraph, measure recall@k against the held-out citations and track a hallucinated-key rate for the generation side. The system logs everything needed to build it.

**"How would you scale it?"**
> Reads: pgvector HNSW handles this corpus comfortably; past a few million chunks, partition or move to a dedicated vector service. Graph: per-hop budgets already bound traversal; add Neo4j read replicas. Ingestion is already async and horizontally scalable (more arq workers). The agent layer is stateless per turn, so it scales with API replicas; session state lives in Postgres.

---

## 7. Resume Bullets

```text
Built CitePilot, an agentic research-writing platform pairing a browser LaTeX
editor with citation-aware GraphRAG: FastAPI, Postgres/pgvector, Neo4j, Redis,
and a typed tool loop streamed to the UI with full tool-call observability.
```

```text
Modeled papers, authors, venues, concepts, and citations as a knowledge graph;
fused vector search with co-citation, bibliographic coupling, and concept-overlap
signals via Reciprocal Rank Fusion to recommend citations with grounded,
feature-derived explanations.
```

```text
Exposed retrieval, citation-graph expansion, BibTeX generation, and versioned
anchor-based LaTeX patching as ten typed MCP tools sharing one registry with the
in-app agent — verified end-to-end from Claude Desktop and MCP Inspector.
```

---

## 8. Three-Minute Demo Script

1. `make up` (already warm). Open CitePilot, create "GraphRAG Literature Review".
2. Search "graph retrieval augmented generation", import 3 papers. *Say: each import also creates stub nodes for every reference, so the citation graph is dense immediately.*
3. Open the graph drawer — seed papers bright, stubs dimmed. Click **Enrich graph**; watch stubs promote. *This is the visual "the KG is alive" moment.*
4. Select the intro paragraph → "Suggest related work citations for this paragraph."
5. Point at the tool trace as it streams: `inspect_latex_project → retrieve_evidence → rank_related_work`. *Say: the agent is a tool loop, not a black box — every call is typed, logged, and visible.*
6. Read one suggestion card's **reason** aloud — "co-cited with X by 7 papers, shares concepts {…}". *Say: reasons are computed from graph features, not generated freeform, so they can't be hallucinated.*
7. Insert the citation → show `\cite{}` + `references.bib` → Compile → PDF.
8. Finale: open MCP Inspector (or Claude Desktop), call `retrieve_evidence` with the same paragraph — same tools, same graph, different client. *Say: capabilities are a layer; the web agent and MCP are just two consumers.*

---

## 9. Suggested Study Order

1. **Before/while the agent builds M4–M5:** read about entity resolution and skim OpenAlex's data model (works, authorships, referenced_works). Hand-write `normalize.py` + `upsert.py`.
2. **M5–M7:** learn Cypher hands-on in the Neo4j browser against your own data — write the co-citation and coupling queries yourself before reading the agent's. Then hand-write `fusion.py` (30 lines) and `hybrid.py`.
3. **M8:** hand-write `orchestrator.py` against `test_agent_stream.py`. This is the single most valuable exercise in the project.
4. **M9:** hand-write `patcher.py` against its tests — small, and it cements the anchored-edit insight.
5. **M11:** hand-write `mcp_server/` (it's short), then actually connect Claude Desktop to it. Read the MCP spec's tools section once, after having built it — it'll click instantly.
6. **Last:** write the README's System Design Notes yourself, from memory, then check against this file. If you can reproduce Section 6 unprompted, you're interview-ready.
