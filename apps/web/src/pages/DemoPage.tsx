import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Bot,
  Braces,
  Eye,
  FilePlus2,
  FileText,
  FlaskConical,
  Loader2,
  Network,
  Plus,
  Send,
  Upload,
  X,
} from "lucide-react";

import { LatexEditor } from "@/components/editor/LatexEditor";
import {
  compileDemo,
  getDemoLimits,
  streamDemoAgent,
  type DemoChatMessage,
  type DemoLimits,
  type DemoPaper,
  type DemoSourceFile,
} from "@/lib/demo";

type DemoProject = {
  id: string;
  name: string;
  description: string;
  accent: string;
  files: DemoSourceFile[];
  papers: DemoPaper[];
};

const graphragBibliography = `@article{edge2024graphrag,
  title={From Local to Global: A GraphRAG Approach},
  author={Edge, Darren and others},
  year={2024}
}

@article{lewis2020rag,
  title={Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks},
  author={Lewis, Patrick and others},
  year={2020}
}

@article{gao2023retrieval,
  title={Retrieval-Augmented Generation for Large Language Models: A Survey},
  author={Gao, Yunfan and others},
  year={2023}
}`;

function starterFiles(name: string, topic: string): DemoSourceFile[] {
  return [
    {
      path: "main.tex",
      content: `\\documentclass{article}
\\usepackage{hyperref}
\\usepackage{cite}
\\title{${name}}
\\author{CitePilot Demo}
\\date{}

\\begin{document}
\\maketitle

\\section{Introduction}
${topic} Retrieval-augmented generation connects claims to relevant evidence \\cite{lewis2020rag}.

\\section{Related Work}
Graph-grounded retrieval can reveal shared foundations that keyword search misses \\cite{edge2024graphrag,gao2023retrieval}.

\\bibliographystyle{plain}
\\bibliography{references}
\\end{document}
`,
    },
    { path: "references.bib", content: graphragBibliography },
  ];
}

const graphragPapers: DemoPaper[] = [
  { key: "lewis2020rag", title: "Retrieval-Augmented Generation", year: 2020, role: "foundation" },
  { key: "gao2023retrieval", title: "RAG for Large Language Models: A Survey", year: 2023, role: "survey" },
  { key: "edge2024graphrag", title: "From Local to Global: A GraphRAG Approach", year: 2024, role: "project" },
];

const agentsBibliography = `@article{yao2023react,
  title={ReAct: Synergizing Reasoning and Acting in Language Models},
  author={Yao, Shunyu and others},
  year={2023}
}

@article{schick2023toolformer,
  title={Toolformer: Language Models Can Teach Themselves to Use Tools},
  author={Schick, Timo and others},
  year={2023}
}

@article{wang2024agentsurvey,
  title={A Survey on Large Language Model Based Autonomous Agents},
  author={Wang, Lei and others},
  year={2024}
}`;

const climateBibliography = `@article{ipcc2023,
  title={Climate Change 2023: Synthesis Report},
  author={{Intergovernmental Panel on Climate Change}},
  year={2023}
}

@article{reichstein2019deep,
  title={Deep Learning and Process Understanding for Data-Driven Earth System Science},
  author={Reichstein, Markus and others},
  year={2019}
}

@article{rolnick2022climate,
  title={Tackling Climate Change with Machine Learning},
  author={Rolnick, David and others},
  year={2022}
}`;

const agentPapers: DemoPaper[] = [
  { key: "yao2023react", title: "ReAct: Synergizing Reasoning and Acting", year: 2023, role: "foundation" },
  { key: "schick2023toolformer", title: "Toolformer", year: 2023, role: "tool use" },
  { key: "wang2024agentsurvey", title: "A Survey on LLM-Based Autonomous Agents", year: 2024, role: "survey" },
];

const climatePapers: DemoPaper[] = [
  { key: "ipcc2023", title: "Climate Change 2023: Synthesis Report", year: 2023, role: "foundation" },
  { key: "reichstein2019deep", title: "Deep Learning for Earth System Science", year: 2019, role: "method" },
  { key: "rolnick2022climate", title: "Tackling Climate Change with Machine Learning", year: 2022, role: "survey" },
];

function seededFiles(main: string, references: string): DemoSourceFile[] {
  return [
    { path: "main.tex", content: main },
    { path: "references.bib", content: references },
  ];
}

const graphragDraft = `\\documentclass{article}
\\usepackage{hyperref}
\\usepackage{cite}
\\title{GraphRAG Beyond the Vector Index: A Working Survey}
\\author{CitePilot Demo}
\\date{}

\\begin{document}
\\maketitle

\\begin{abstract}
Retrieval-augmented generation grounds model outputs in external evidence, but conventional vector
retrieval often treats documents as independent fragments. This working survey examines graph-based
retrieval as a way to preserve relationships among entities, claims, and sources. We compare local
neighborhood retrieval, global community summaries, and hybrid graph-vector pipelines.
\\end{abstract}

\\section{Introduction}
Retrieval-augmented generation (RAG) separates factual storage from model parameters by retrieving
evidence at inference time \\cite{lewis2020rag}. The pattern improves provenance and makes knowledge
easier to update, yet chunk-level vector search is weaker when an answer requires connecting facts
distributed across documents.

GraphRAG systems add explicit structure. Documents become entities, relationships, claims, or
communities, and retrieval can follow those connections instead of ranking each chunk independently
\\cite{edge2024graphrag}. This survey asks when that structure produces better evidence and when it
merely adds indexing cost.

\\section{Retrieval Families}
\\subsection{Vector-first retrieval}
Dense retrievers embed questions and passages into a shared space. They remain a strong production
baseline, especially when paired with query rewriting and reranking \\cite{gao2023retrieval}.

\\subsection{Local graph retrieval}
Local approaches match an entity or passage and expand through a bounded neighborhood. Adjacent
claims, citations, and aliases can expose evidence that would not rank highly in vector space.

\\subsection{Global graph retrieval}
Global questions ask for themes or disagreements across a collection. Community summaries provide a
hierarchical view of the corpus, trading a larger indexing phase for broader evidence coverage.

\\section{Evaluation}
A fair comparison should hold the generator constant and vary only retrieval. We propose measuring
answer correctness, citation precision, evidence coverage, latency, and index construction cost.
Multi-hop questions should be reported separately because aggregate scores can hide the cases where
graph structure is most valuable.

\\section{Discussion}
Graph retrieval is unlikely to replace vector search universally. Hybrid systems are more plausible:
vector search provides a high-recall entry point while graph expansion supplies connected context.
Open problems include graph freshness, uncertainty in extracted edges, and benchmarks with
claim-level provenance.

\\section{Conclusion}
GraphRAG is best understood as a family of retrieval designs. Its promise is relational evidence:
not only finding relevant text, but preserving why pieces of evidence belong together.

\\bibliographystyle{plain}
\\bibliography{references}
\\end{document}
`;

const agentsHalfDraft = `\\documentclass{article}
\\usepackage{hyperref}
\\usepackage{cite}
\\title{Reliable Tool-Using Agents Under Partial Failure}
\\author{CitePilot Demo}
\\date{}

\\begin{document}
\\maketitle

\\begin{abstract}
Tool-using language model agents can search, calculate, and modify external state, but each capability
introduces a new failure boundary. This half-written paper develops a reliability model for agents
that must act under incomplete observations and intermittent tool errors.
\\end{abstract}

\\section{Introduction}
Agent systems interleave model reasoning with actions. ReAct combined reasoning traces and actions in
one loop \\cite{yao2023react}, while Toolformer studied how models learn when API calls are useful
\\cite{schick2023toolformer}. Deployment also requires predictable behavior when a tool times out,
returns malformed data, or succeeds after the agent has already changed its plan.

We focus on the orchestration layer. The question is not whether a model can select a tool once, but
whether the system preserves intent across retries, partial results, and human review.

\\section{Related Work}
Agent surveys commonly separate planning, memory, tool use, and action modules
\\cite{wang2024agentsurvey}. Failures cross those boundaries: a stale observation can corrupt a plan,
and an ambiguous response can be stored as a fact.

\\section{System Model}
We represent a turn as the user goal, adopted observations, pending tool calls, and a monotonic action
log. Tool results are successful, retryable, terminal, or ambiguous. Ambiguous outcomes require
inspection before another state-changing call is allowed.

% TODO: Add the state transition figure and define the recovery budget formally.

\\section{Failure Taxonomy}
\\subsection{Observation failures}
Missing fields and stale reads should be treated as evidence-quality problems.

\\subsection{Action failures}
Timeouts are difficult because the caller may not know whether an action took effect. Idempotency
keys and post-action inspection reduce duplicate writes.

\\subsection{Planning failures}
% TODO: Compare plan repair with full replanning and add two benchmark traces.

\\section{Evaluation Plan}
We will compare no recovery, fixed retries, and state-aware recovery. Primary metrics will include
task completion, duplicate side effects, unsupported claims, tool calls per completed task, and the
fraction of failures correctly escalated to a human.

% TODO: Results, limitations, and conclusion are intentionally unfinished.

\\bibliographystyle{plain}
\\bibliography{references}
\\end{document}
`;

const climateOutline = `\\documentclass{article}
\\usepackage{hyperref}
\\usepackage{cite}
\\title{Evidence-Aware Climate Risk Modeling: Research Outline}
\\author{CitePilot Demo}
\\date{}

\\begin{document}
\\maketitle

\\section{Motivation}
Climate risk models combine physical projections, exposure data, and assumptions about adaptation.
The IPCC describes risk as an interaction among hazards, vulnerability, and exposure
\\cite{ipcc2023}. Machine learning can connect heterogeneous data, but predictive accuracy alone does
not make a model useful for policy.

\\section{Research Questions}
\\begin{enumerate}
  \\item How should source uncertainty propagate into a local risk estimate?
  \\item Which explanations remain stable across climate scenarios?
  \\item Can a citation graph reveal features derived from the same underlying dataset?
\\end{enumerate}

\\section{Proposed Method}
The planned system will pair a tabular risk model with an evidence layer recording the source,
geographic scope, and publication date of each feature. Process-aware machine learning may constrain
predictions outside the observed range \\cite{reichstein2019deep}. The design follows recommendations
for using machine learning as one component of climate action \\cite{rolnick2022climate}.

% TODO: Select a region and replace this outline with a concrete data inventory.
% TODO: Add baselines, validation splits, and an uncertainty calibration plan.

\\section{Planned Paper Structure}
\\begin{enumerate}
  \\item Introduction and decision context
  \\item Data provenance and citation graph
  \\item Risk model and uncertainty propagation
  \\item Scenario-based evaluation
  \\item Limitations and responsible use
\\end{enumerate}

\\bibliographystyle{plain}
\\bibliography{references}
\\end{document}
`;

const SEEDED_PROJECTS: DemoProject[] = [
  {
    id: "demo-graphrag",
    name: "GraphRAG Survey",
    description: "A developed working draft comparing graph, vector, and hybrid retrieval.",
    accent: "from-indigo-500 to-violet-500",
    files: seededFiles(graphragDraft, graphragBibliography),
    papers: graphragPapers,
  },
  {
    id: "demo-agents",
    name: "Reliable AI Agents",
    description: "A half-written paper with a system model, evaluation plan, and open TODOs.",
    accent: "from-cyan-500 to-blue-500",
    files: seededFiles(agentsHalfDraft, agentsBibliography),
    papers: agentPapers,
  },
  {
    id: "demo-climate",
    name: "Climate Risk Modeling",
    description: "An early research outline with questions, methods, and a planned paper structure.",
    accent: "from-emerald-500 to-teal-500",
    files: seededFiles(climateOutline, climateBibliography),
    papers: climatePapers,
  },
];

function LimitPill({ icon: Icon, label, remaining, limit }: { icon: typeof Bot; label: string; remaining?: number; limit?: number }) {
  return <span className="inline-flex items-center gap-1.5 rounded-full border border-edge-2 bg-ink-800 px-2.5 py-1 text-[10px] text-mist"><Icon className="h-3 w-3 text-indigo-300" />{label} {remaining ?? "–"}/{limit ?? "–"}</span>;
}

function DemoGraph({ project }: { project: DemoProject }) {
  return (
    <div className="relative h-full min-h-[480px] overflow-hidden bg-ink-950 p-6">
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
        <line x1="25%" y1="30%" x2="50%" y2="52%" stroke="#22d3ee" strokeWidth="2" opacity=".7" />
        <line x1="76%" y1="28%" x2="50%" y2="52%" stroke="#a78bfa" strokeWidth="2" opacity=".7" />
        <line x1="50%" y1="52%" x2="62%" y2="80%" stroke="#fbbf24" strokeWidth="2" opacity=".7" />
      </svg>
      <div className="absolute left-[39%] top-[42%] w-56 rounded-xl border border-indigo-400/60 bg-indigo-500/15 p-4 shadow-xl"><p className="text-[10px] font-semibold uppercase text-indigo-200">Current project</p><p className="mt-1 text-sm font-semibold text-snow">{project.name}</p><p className="mt-2 text-[10px] text-fog">3 connected sources</p></div>
      {project.papers.map((paper, index) => {
        const positions = ["left-[10%] top-[20%]", "right-[8%] top-[18%]", "left-[54%] bottom-[8%]"];
        return <div key={paper.key} className={`absolute ${positions[index]} w-52 rounded-lg border border-edge-2 bg-ink-800/95 p-3 shadow-lg`}><p className="line-clamp-2 text-xs font-medium text-snow">{paper.title}</p><p className="mt-1 font-mono text-[10px] text-cyan-300">{paper.year} · {paper.role}</p><p className="mt-2 text-[10px] text-fog">@{paper.key}</p></div>;
      })}
      <div className="absolute bottom-4 left-4 rounded-lg border border-edge bg-ink-900/90 px-3 py-2 text-[10px] text-fog">Interactive graph expansion is reserved for signed-in projects. This sample shows citation roles and shared foundations.</div>
    </div>
  );
}

function DemoWorkspace({ project, onBack, onSignUp }: { project: DemoProject; onBack: () => void; onSignUp: () => void }) {
  const [files, setFiles] = useState(project.files);
  const [activePath, setActivePath] = useState("main.tex");
  const [selectedText, setSelectedText] = useState("");
  const [tab, setTab] = useState<"editor" | "graph" | "preview">("editor");
  const [limits, setLimits] = useState<DemoLimits | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [compiling, setCompiling] = useState(false);
  const [messages, setMessages] = useState<DemoChatMessage[]>([]);
  const [message, setMessage] = useState("");
  const [agentRunning, setAgentRunning] = useState(false);
  const [toolActivity, setToolActivity] = useState("");
  const [pendingPatch, setPendingPatch] = useState<{ path: string; before: string; after: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const importRef = useRef<HTMLInputElement | null>(null);
  const activeFile = files.find((file) => file.path === activePath) ?? files[0];

  useEffect(() => { void getDemoLimits().then(setLimits).catch(() => undefined); }, []);
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  async function preview() {
    if (compiling || limits?.preview_remaining === 0) return;
    setCompiling(true); setPreviewError("");
    try {
      const result = await compileDemo(files);
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
      setPdfUrl(URL.createObjectURL(result.pdf));
      setLimits((current) => current ? { ...current, preview_remaining: result.remaining } : current);
      setTab("preview");
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "Preview failed");
      void getDemoLimits().then(setLimits).catch(() => undefined);
    } finally { setCompiling(false); }
  }

  async function runAgent(prompt?: string) {
    const text = (prompt ?? message).trim();
    if (!text || agentRunning || limits?.agent_remaining === 0) return;
    const prior = messages.slice(-6);
    setMessages((current) => [...current, { role: "user", content: text }, { role: "assistant", content: "" }]);
    setMessage(""); setAgentRunning(true);
    const controller = new AbortController(); abortRef.current = controller;
    try {
      await streamDemoAgent({ project_name: project.name, files, papers: project.papers, message: text, active_file_path: activePath, selected_text: selectedText || undefined, conversation: prior }, (event) => {
        if (event.event === "message_delta") {
          const chunk = typeof event.data.text === "string" ? event.data.text : "";
          setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: item.content + chunk } : item));
        }
        if (event.event === "usage" || event.event === "done") {
          const remaining = Number(event.data.agent_remaining);
          if (Number.isFinite(remaining)) setLimits((current) => current ? { ...current, agent_remaining: remaining } : current);
        }
        if (event.event === "tool_call") setToolActivity(`Using ${String(event.data.tool_name ?? "project tool")}…`);
        if (event.event === "tool_result") setToolActivity(String(event.data.summary ?? "Tool completed"));
        if (event.event === "patch_proposal") {
          const preview = event.data.preview;
          if (preview && typeof preview === "object" && "path" in preview && "before" in preview && "after" in preview) {
            const candidate = preview as Record<string, unknown>;
            if (typeof candidate.path === "string" && typeof candidate.before === "string" && typeof candidate.after === "string") {
              setPendingPatch({ path: candidate.path, before: candidate.before, after: candidate.after });
            }
          }
        }
        if (event.event === "error") {
          setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: String(event.data.message ?? "Agent unavailable") } : item));
          const remaining = Number(event.data.agent_remaining);
          if (Number.isFinite(remaining)) setLimits((current) => current ? { ...current, agent_remaining: remaining } : current);
        }
      }, controller.signal);
    } catch (error) {
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: error instanceof Error ? error.message : "Agent failed" } : item));
      void getDemoLimits().then(setLimits).catch(() => undefined);
    } finally { setAgentRunning(false); abortRef.current = null; }
  }

  return (
    <main className="flex h-screen min-h-[680px] flex-col bg-ink-950">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-edge px-4 py-3">
        <button onClick={onBack} className="flex items-center gap-2 text-xs text-fog hover:text-snow"><ArrowLeft className="h-4 w-4" /> Demo projects</button>
        <div className="min-w-0"><p className="truncate text-sm font-semibold text-snow">{project.name}</p><p className="text-[10px] text-amber-200">Ephemeral sandbox · changes disappear on refresh</p></div>
        <div className="flex items-center gap-2"><LimitPill icon={Bot} label="Agent" remaining={limits?.agent_remaining} limit={limits?.agent_limit} /><LimitPill icon={Eye} label="Previews" remaining={limits?.preview_remaining} limit={limits?.preview_limit} /><button onClick={onSignUp} className="rounded-lg bg-accent-deep px-3 py-1.5 text-xs font-semibold text-white">Save real projects</button></div>
      </header>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[210px_minmax(0,1fr)_320px]">
        <aside className="overflow-auto border-r border-edge bg-ink-900 p-3">
          <div className="flex items-center justify-between"><p className="text-[10px] font-semibold uppercase tracking-wider text-fog">Files</p><button title="Import local files" onClick={() => importRef.current?.click()} className="rounded p-1 text-fog hover:bg-ink-800 hover:text-snow"><Upload className="h-3.5 w-3.5" /></button></div>
          <input ref={importRef} hidden multiple type="file" accept=".tex,.bib,.sty,.cls,.txt" onChange={async (event) => { const incoming = await Promise.all(Array.from(event.target.files ?? []).slice(0, 8).map(async (file) => ({ path: file.name, content: await file.text() }))); setFiles((current) => { const paths = new Set(incoming.map((file) => file.path)); return [...current.filter((file) => !paths.has(file.path)), ...incoming]; }); event.target.value = ""; }} />
          <div className="mt-2 space-y-1">{files.map((file) => <button key={file.path} onClick={() => { setActivePath(file.path); setTab("editor"); }} className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs ${activePath === file.path ? "bg-indigo-500/10 text-indigo-200" : "text-mist hover:bg-ink-800"}`}><FileText className="h-3.5 w-3.5" /><span className="truncate">{file.path}</span></button>)}</div>
          <button onClick={() => { const path = `notes-${files.length + 1}.tex`; setFiles((current) => [...current, { path, content: "% Temporary demo file\n" }]); setActivePath(path); setTab("editor"); }} className="mt-2 flex w-full items-center gap-2 rounded-md border border-dashed border-edge-2 px-2 py-2 text-xs text-fog hover:text-snow"><FilePlus2 className="h-3.5 w-3.5" />New file</button>
          <p className="mt-6 text-[10px] font-semibold uppercase tracking-wider text-fog">Project papers</p>
          <div className="mt-2 space-y-2">{project.papers.map((paper) => <button key={paper.key} onClick={() => setTab("graph")} className="w-full rounded-lg border border-edge bg-ink-800 p-2 text-left"><p className="line-clamp-2 text-[11px] text-mist">{paper.title}</p><p className="mt-1 font-mono text-[9px] text-cyan-300">@{paper.key}</p></button>)}</div>
        </aside>
        <section className="flex min-w-0 flex-col border-r border-edge">
          <div className="flex h-11 items-center justify-between border-b border-edge bg-ink-900 px-3"><div className="flex gap-1">{(["editor", "graph", "preview"] as const).map((item) => <button key={item} onClick={() => setTab(item)} className={`rounded-md px-3 py-1.5 text-xs capitalize ${tab === item ? "bg-ink-700 text-snow" : "text-fog hover:text-mist"}`}>{item}</button>)}</div><button onClick={() => void preview()} disabled={compiling || limits?.preview_remaining === 0} className="flex items-center gap-2 rounded-md bg-indigo-500/15 px-3 py-1.5 text-xs font-semibold text-indigo-200 disabled:opacity-40">{compiling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}{compiling ? "Compiling…" : "Refresh preview"}</button></div>
          <div className="min-h-0 flex-1">{tab === "editor" && activeFile ? <LatexEditor value={activeFile.content} path={activeFile.path} onSelectionChange={setSelectedText} onChange={(content) => setFiles((current) => current.map((file) => file.path === activeFile.path ? { ...file, content } : file))} /> : null}{tab === "graph" ? <DemoGraph project={project} /> : null}{tab === "preview" ? <div className="flex h-full flex-col bg-ink-850 p-3">{previewError ? <div className="m-auto max-w-lg rounded-lg border border-red-400/25 bg-red-400/5 p-4 text-xs text-red-300">{previewError}</div> : pdfUrl ? <><div className="mb-2 text-center text-[10px] text-fog">Preview only · generated temporarily · no download action is provided</div><iframe title="Temporary LaTeX preview" src={`${pdfUrl}#toolbar=0&navpanes=0`} className="min-h-0 flex-1 rounded-lg border border-edge bg-white" /></> : <div className="m-auto text-center"><Braces className="mx-auto h-7 w-7 text-fog" /><p className="mt-3 text-sm text-mist">Compile your draft to see a temporary PDF.</p></div>}</div> : null}</div>
        </section>
        <aside className="flex min-h-0 flex-col bg-ink-900">
          <div className="flex h-11 items-center justify-between gap-2 border-b border-edge px-4"><span className="flex items-center gap-2"><Bot className="h-4 w-4 text-indigo-300" /><span className="text-xs font-semibold text-snow">Demo research agent</span></span>{toolActivity ? <span className="max-w-36 truncate text-[9px] text-cyan-300">{toolActivity}</span> : null}</div>
          <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">{messages.length === 0 ? <><div className="rounded-lg border border-indigo-400/20 bg-indigo-400/5 p-3 text-xs leading-5 text-mist">Ask about the draft, citations, graph, or a selected passage. Demo mode uses CitePilot's bounded tool loop with ephemeral inspection, retrieval, graph, and reviewable patch tools.</div>{["Suggest citations for the introduction.", "Explain this project's citation graph.", "Improve the selected LaTeX passage."].map((prompt) => <button key={prompt} onClick={() => void runAgent(prompt)} className="block w-full rounded-lg border border-edge bg-ink-800 px-3 py-2 text-left text-[11px] text-fog hover:border-indigo-400/30 hover:text-mist">{prompt}</button>)}</> : messages.map((item, index) => <div key={index} className={`rounded-lg px-3 py-2 text-xs leading-5 ${item.role === "user" ? "ml-6 bg-indigo-500/15 text-indigo-100" : "mr-3 bg-ink-800 text-mist"}`}>{item.content || <span className="inline-flex items-center gap-2 text-fog"><Loader2 className="h-3 w-3 animate-spin" />Thinking…</span>}</div>)}</div>
          {pendingPatch ? <div className="border-t border-edge bg-indigo-500/5 p-3"><p className="text-[10px] font-semibold text-indigo-200">Review agent edit · {pendingPatch.path}</p><p className="mt-1 text-[9px] text-fog">The edit is still only in memory and has not been applied.</p><div className="mt-2 flex gap-2"><button type="button" onClick={() => { setFiles((current) => current.map((file) => file.path === pendingPatch.path && file.content === pendingPatch.before ? { ...file, content: pendingPatch.after } : file)); setActivePath(pendingPatch.path); setTab("editor"); setPendingPatch(null); }} className="rounded bg-accent-deep px-2 py-1 text-[10px] font-semibold text-white">Apply in demo</button><button type="button" onClick={() => setPendingPatch(null)} className="rounded border border-edge-2 px-2 py-1 text-[10px] text-fog">Discard</button></div></div> : null}
          <form onSubmit={(event) => { event.preventDefault(); void runAgent(); }} className="border-t border-edge p-3"><div className="flex gap-2"><textarea value={message} onChange={(event) => setMessage(event.target.value)} disabled={agentRunning || limits?.agent_remaining === 0} placeholder={limits?.agent_remaining === 0 ? "Demo agent limit reached" : "Ask about this project…"} className="min-h-16 min-w-0 flex-1 resize-none rounded-lg border border-edge-2 bg-ink-800 px-3 py-2 text-xs text-snow outline-none focus:border-indigo-400/50" /><button disabled={!message.trim() || agentRunning || limits?.agent_remaining === 0} className="self-end rounded-lg bg-accent-deep p-2.5 text-white disabled:opacity-40"><Send className="h-4 w-4" /></button></div><p className="mt-2 text-center text-[9px] text-fog">No chat history or project content is stored.</p></form>
        </aside>
      </div>
    </main>
  );
}

export function DemoPage({ onExit, onSignUp }: { onExit: () => void; onSignUp: () => void }) {
  const [open, setOpen] = useState<DemoProject | null>(() => {
    const requested = new URLSearchParams(window.location.search).get("demo_project");
    return SEEDED_PROJECTS.find((project) => project.id === requested) ?? null;
  });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [createdUsed, setCreatedUsed] = useState(() => sessionStorage.getItem("citepilot_demo_project_created") === "1");
  const [createdProject, setCreatedProject] = useState<DemoProject | null>(null);
  const projects = createdProject ? [...SEEDED_PROJECTS, createdProject] : SEEDED_PROJECTS;

  if (open) {
    return <DemoWorkspace project={open} onBack={() => setOpen(null)} onSignUp={onSignUp} />;
  }

  return (
    <main className="min-h-screen bg-ink-950">
      <header className="border-b border-edge bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <button onClick={onExit} className="flex items-center gap-2 text-xs text-fog hover:text-snow">
            <ArrowLeft className="h-4 w-4" /> Showcase
          </button>
          <div className="flex items-center gap-2 text-sm font-bold text-snow">
            <FlaskConical className="h-4 w-4 text-amber-300" /> CitePilot demo
          </div>
          <button onClick={onSignUp} className="rounded-lg border border-indigo-400/40 px-3 py-1.5 text-xs font-semibold text-indigo-200 hover:bg-indigo-400/10">
            Sign in
          </button>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-12">
        <div className="max-w-2xl">
          <span className="rounded-full border border-amber-400/20 bg-amber-400/5 px-3 py-1 text-[10px] font-semibold text-amber-200">
            LIVE SANDBOX · NO PROJECT DATABASE WRITES
          </span>
          <h1 className="mt-5 text-3xl font-bold tracking-tight text-snow">Use CitePilot without an account.</h1>
          <p className="mt-3 text-sm leading-6 text-fog">
            Edit and import LaTeX, explore a citation graph, run the research agent, and compile
            temporary PDF previews. You get one custom project, three agent turns, and three previews.
          </p>
        </div>

        <div className="mt-9 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <button
              key={project.id}
              onClick={() => setOpen(project)}
              className="group overflow-hidden rounded-xl border border-edge bg-ink-900 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-400/40"
            >
              <div className={`h-1.5 bg-gradient-to-r ${project.accent}`} />
              <div className="p-5">
                <Network className="h-5 w-5 text-indigo-300" />
                <h2 className="mt-4 text-sm font-semibold text-snow">{project.name}</h2>
                <p className="mt-2 min-h-10 text-xs leading-5 text-fog">{project.description}</p>
                <div className="mt-5 flex gap-4 border-t border-edge pt-3 text-[10px] text-fog">
                  <span>{project.files.length} files</span><span>{project.papers.length} papers</span>
                </div>
              </div>
            </button>
          ))}
          <button
            disabled={createdUsed}
            onClick={() => setCreating(true)}
            className="grid min-h-52 place-items-center rounded-xl border border-dashed border-edge-2 p-5 text-center hover:border-indigo-400/50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <div>
              <Plus className="mx-auto h-6 w-6 text-indigo-300" />
              <h2 className="mt-3 text-sm font-semibold text-snow">
                {createdUsed ? "Custom project limit reached" : "Create one temporary project"}
              </h2>
              <p className="mt-2 text-xs text-fog">Files remain in memory for this page only.</p>
            </div>
          </button>
        </div>
      </section>

      {creating ? (
        <div className="fixed inset-0 grid place-items-center bg-snow/60 p-5 backdrop-blur-sm">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const clean = name.trim();
              const project: DemoProject = {
                id: crypto.randomUUID(),
                name: clean,
                description: "Your one temporary CitePilot project.",
                accent: "from-fuchsia-500 to-indigo-500",
                files: starterFiles(clean, "This temporary review explores an emerging research question."),
                papers: graphragPapers,
              };
              sessionStorage.setItem("citepilot_demo_project_created", "1");
              setCreatedUsed(true);
              setCreatedProject(project);
              setCreating(false);
              setName("");
              setOpen(project);
            }}
            className="w-full max-w-sm rounded-xl border border-edge bg-ink-900 p-5 shadow-lg"
          >
            <div className="flex justify-between">
              <h2 className="text-sm font-semibold text-snow">One temporary project</h2>
              <button type="button" onClick={() => setCreating(false)}><X className="h-4 w-4 text-fog" /></button>
            </div>
            <label className="mt-5 block text-xs text-mist">
              Project name
              <input autoFocus required value={name} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-lg border border-edge-2 bg-ink-800 px-3 py-2 text-sm text-snow outline-none focus:border-indigo-400" />
            </label>
            <p className="mt-3 text-[10px] leading-4 text-amber-200">
              The project and its files are never sent to persistence APIs. Closing or refreshing discards them.
            </p>
            <button className="mt-5 w-full rounded-lg bg-accent-deep px-3 py-2 text-xs font-semibold text-white">Open temporary workspace</button>
          </form>
        </div>
      ) : null}
    </main>
  );
}
