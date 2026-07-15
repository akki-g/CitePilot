import { expect, test } from "@playwright/test";

const files = [
  {
    id: "file-main",
    path: "main.tex",
    version: 3,
    content: String.raw`\documentclass{article}
\usepackage{hyperref}
\usepackage{cite}

\title{GraphRAG Literature Review}
\author{CitePilot}
\date{\today}

\begin{document}
\maketitle

\section{Introduction}
Graph retrieval augmented generation needs citation-aware evidence, not only semantic similarity.

\bibliographystyle{plain}
\bibliography{references}

\end{document}`,
  },
  {
    id: "file-bib",
    path: "references.bib",
    version: 1,
    content: "@article{lewis2020rag,\n  title={Retrieval augmented generation},\n  year={2020}\n}\n",
  },
];

const papers = [
  {
    paper_id: "paper-seed",
    bibtex_key: "lewis2020rag",
    title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    year: 2020,
    cited_by_count: 4822,
    is_stub: false,
  },
  {
    paper_id: "paper-graph",
    bibtex_key: "edge2024graphrag",
    title: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
    year: 2024,
    cited_by_count: 628,
    is_stub: false,
  },
  {
    paper_id: "paper-stub",
    bibtex_key: "stub2023",
    title: "Citation Graph Reasoning with Incomplete Metadata",
    year: 2023,
    cited_by_count: 77,
    is_stub: true,
  },
];

const graph = {
  nodes: [
    {
      id: "paper-seed",
      title: "Retrieval-Augmented Generation",
      year: 2020,
      cited_by_count: 4822,
      is_stub: false,
      is_seed: true,
    },
    {
      id: "paper-graph",
      title: "Graph RAG Summarization",
      year: 2024,
      cited_by_count: 628,
      is_stub: false,
      is_seed: false,
    },
    {
      id: "paper-stub",
      title: "Incomplete Citation Metadata",
      year: 2023,
      cited_by_count: 77,
      is_stub: true,
      is_seed: false,
    },
  ],
  edges: [
    { source: "paper-graph", target: "paper-seed", type: "CITES" },
    { source: "paper-seed", target: "paper-stub", type: "CITES" },
  ],
  ranked_neighbors: [],
  summary: "neighborhood has 3 papers, 2 citation edges",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    let body: unknown = { detail: "mocked endpoint not implemented" };
    let status = 404;

    if (url.pathname === "/api/health") {
      body = { status: "ok", postgres: "ok", neo4j: "ok", redis: "ok" };
      status = 200;
    } else if (url.pathname === "/api/projects" && method === "GET") {
      body = [
        {
          id: "p1",
          name: "GraphRAG Literature Review",
          description: "Citation-aware related work draft",
          created_at: "2026-07-05T12:00:00Z",
          updated_at: "2026-07-05T12:00:00Z",
        },
      ];
      status = 200;
    } else if (url.pathname === "/api/projects/p1/files") {
      body = files;
      status = 200;
    } else if (url.pathname === "/api/projects/p1/papers") {
      body = papers;
      status = 200;
    } else if (url.pathname === "/api/graph/neighborhood") {
      body = graph;
      status = 200;
    } else if (url.pathname === "/api/agent/stream") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'event: message_delta\ndata: {"text":"I found two strong GraphRAG citation candidates."}\n\n',
          'event: tool_call\ndata: {"tool_name":"retrieve_evidence","arguments":{"limit":8}}\n\n',
          'event: tool_result\ndata: {"tool_name":"retrieve_evidence","summary":"found candidate papers"}\n\n',
          'event: done\ndata: {"session_id":"session-1"}\n\n',
        ].join(""),
      });
      return;
    }

    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
});

test("workspace renders with mocked backend data", async ({ page }) => {
  await page.goto("http://localhost:3000");
  await page.getByRole("button", { name: /GraphRAG Literature Review/ }).click();
  await expect(page.locator(".cm-editor")).toBeVisible();
  await expect(page.getByText("CitePilot Agent")).toBeVisible();
  await expect(page.getByRole("button", { name: "LaTeX" })).toHaveClass(/bg-slate-950/);
  await page.getByPlaceholder("Ask about citations, edits, or evidence...").fill("Give me a citation plan.");
  await page.getByLabel("Send message").click();
  await expect(page.getByText("Give me a citation plan.").nth(1)).toBeVisible();
  await expect(page.getByText("I found two strong GraphRAG citation candidates.")).toBeVisible();
  await expect(page.getByText("Tool trace")).toBeVisible();
  await page.getByLabel("New chat").click();
  await expect(page.getByText("New conversation").first()).toBeVisible();
  await page.getByRole("button", { name: "Hide chat" }).click();
  await expect(page.getByRole("button", { name: "Open chat" })).toBeVisible();
  await page.getByRole("button", { name: "Open chat" }).click();
  await page.getByLabel("Dock chat left").click();
  await page.getByRole("button", { name: "Citation graph" }).click();
  await expect(page.getByRole("heading", { name: "Citation graph" })).toBeVisible();
  await expect(page.getByText("Citation Graph Reasoning with Incomplete Metadata")).toHaveCount(0);
  await page.getByRole("button", { name: "PDF" }).click();
  await expect(page.getByRole("heading", { name: "PDF preview" })).toBeVisible();
  await page.screenshot({ path: "output/playwright/citepilot-workspace-desktop.png", fullPage: true });
});

test("workspace mobile layout is stacked and readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.goto("http://localhost:3000");
  await page.getByRole("button", { name: /GraphRAG Literature Review/ }).click();
  await expect(page.locator(".cm-editor")).toBeVisible();
  await page.getByRole("button", { name: "Citation graph" }).click();
  await expect(page.getByRole("heading", { name: "Citation graph" })).toBeVisible();
  await page.screenshot({ path: "output/playwright/citepilot-workspace-mobile.png", fullPage: true });
});
