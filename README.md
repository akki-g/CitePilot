# CitePilot

**LaTeX writing with citation-aware GraphRAG.** An Overleaf-style workspace where an AI research agent recommends citations by fusing semantic search with the citation graph itself — because the papers you must cite are often structurally related to your work without being textually similar.

## What it does

- **Write** LaTeX in a versioned CodeMirror editor; compile to PDF with sandboxed Tectonic.
- **Import** papers from OpenAlex; every reference becomes a stub row + citation edge immediately, so the graph is dense from the first import.
- **Retrieve** citation-worthy papers for any paragraph: five independent ranked lists (vector similarity + co-citation + bibliographic coupling + shared concepts + citation neighbors) fused with Reciprocal Rank Fusion.
- **Explain** every recommendation with reasons computed from graph features — never LLM-generated, so they can't be hallucinated.
- **Edit safely**: the agent proposes anchor-based patches that a human approves in the UI; wrong anchors fail loudly instead of corrupting files.
- **Expose** the same ten typed tools to any MCP client (Claude Desktop, MCP Inspector) with zero duplicated logic.
- **Return securely** with Google OpenID Connect or a verified email/password account; every saved project is owner-scoped.
- **Showcase safely** with a no-login demo whose seeded and visitor-created projects exist only in browser memory.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Vite + React 19 + TypeScript, TanStack Query, Zustand, CodeMirror, XYFlow, Tailwind v4 |
| API | FastAPI (async), SSE streaming agent |
| Truth store | Postgres 16 + pgvector (HNSW) |
| Graph mirror | Neo4j 5 (derived — rebuildable via `make resync-graph`) |
| Queue / cache | Redis + arq workers |
| LaTeX | Tectonic (network-free, bundle pre-warmed at image build) |
| LLM | Provider-agnostic adapters (Anthropic / OpenAI), bounded 8-iteration tool loop |

## Quickstart

```bash
cp .env.example .env   # then fill in: OPENALEX_MAILTO, LLM_API_KEY, EMBEDDING_API_KEY
make up                # docker compose up --build (first build takes a few minutes)
make migrate           # alembic upgrade head (run once, in a second terminal)
open http://localhost:3000
```

Without an email provider, development signup returns an explicit local verification link in the
browser; it never pretends an email was sent. For real delivery, set `RESEND_API_KEY` plus a
verified `SMTP_FROM_EMAIL`, or configure the SMTP fields. Google sign-in is always visible on the
login page and becomes active after `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are configured.

Verify: `curl http://localhost:8000/api/health` → all stores `"ok"`.

## Development

```bash
make test-backend      # pytest inside the backend container
make resync-graph      # wipe Neo4j and rebuild it from Postgres (proves it's derived)
make logs              # tail all services
cd apps/web && pnpm dev  # frontend outside Docker if preferred
```

MCP server (stdio): `npx @modelcontextprotocol/inspector docker compose exec -T backend python -m app.mcp_server.server`

## EC2 deployment

Production uses a separate, bind-mount-free Compose stack, a same-origin web/API gateway, automatic
database backups, health-gated rollback, and GitHub Actions deployment through AWS OIDC + Systems
Manager rather than stored SSH or AWS keys. Follow
[`infra/deploy/README.md`](infra/deploy/README.md) for the one-time EC2, DNS, IAM, OAuth, email, and
personal-site proxy setup. After that setup, pushes to `main` test and deploy automatically.

## Production authentication

Run `make migrate` after deploying this version, then configure the authentication section from
`.env.example`. A production process refuses to start unless all of these safeguards are present:

- a unique `AUTH_SECRET` of at least 32 characters;
- HTTPS frontend and backend URLs with `SESSION_COOKIE_SECURE=true`;
- Google OAuth credentials and either a Resend API key or working SMTP sender settings.

In Google Cloud, register this exact redirect URI:

```text
https://YOUR_API_HOST/api/auth/oauth/google/callback
```

Set `FRONTEND_URL` to the exact public frontend origin and build the web app with
`VITE_API_BASE_URL=https://YOUR_API_HOST`. The API allows credentials only from that origin.
Login sessions are opaque random tokens stored as HttpOnly, SameSite cookies; only their SHA-256
hashes are stored in Postgres. Unsafe API requests also require a session-bound CSRF token.
Passwords use Argon2, email verification links are single-use and expiring, and OAuth identity is
accepted only when Google reports the email as verified.

For the recommended email setup, verify a sending domain with Resend, then set:

```text
RESEND_API_KEY=re_...
SMTP_FROM_EMAIL=CitePilot <verify@updates.YOUR_DOMAIN>
```

The API waits for the provider to accept the verification message before telling the browser that
it was sent. Provider errors remain retryable through the login page's resend action.

For a personal site, the most reliable arrangement is a first-party subdomain such as
`citepilot.yourdomain.com`, linked from a portfolio page. If you embed it in an iframe, keep the app
and API on same-site subdomains and allow the frame in your reverse proxy's CSP; cross-site browser
cookie restrictions can otherwise break login. The demo remains safe to expose at `/?demo=1`:
projects, files, and chat stay in page memory. Its public endpoints only perform stateless agent
inference and temporary compilation; the compiler work directory is deleted before the response.
Redis stores anonymous 24-hour quota counters, not demo content. The default allowance is one
visitor-created project, three agent turns, and three inline PDF previews.

## Architecture in one paragraph

Postgres is the single source of truth; Neo4j is a derived mirror used only for relationship traversal. Ingestion normalizes every provider into one DTO, dedupes by DOI → provider ID → title+year, and enriches existing rows in place (stubs promote without losing their UUID or edges). Retrieval keeps five signals as independent ranked lists until rank-only RRF fuses them — no scale-mixing, one parameter. The agent is a bounded tool loop where tool errors are data fed back to the model, every call is audited to `tool_calls`, and file edits are exact-anchor patches gated by version checks and (in the web UI) human approval.
