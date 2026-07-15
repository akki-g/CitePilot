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

const bibliography = `@article{edge2024graphrag,
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
    { path: "references.bib", content: bibliography },
  ];
}

const papers: DemoPaper[] = [
  { key: "lewis2020rag", title: "Retrieval-Augmented Generation", year: 2020, role: "foundation" },
  { key: "gao2023retrieval", title: "RAG for Large Language Models: A Survey", year: 2023, role: "survey" },
  { key: "edge2024graphrag", title: "From Local to Global: A GraphRAG Approach", year: 2024, role: "project" },
];

const SEEDED_PROJECTS: DemoProject[] = [
  { id: "demo-graphrag", name: "GraphRAG Survey", description: "Map retrieval-augmented generation across graph and vector methods.", accent: "from-indigo-500 to-violet-500", files: starterFiles("GraphRAG Survey", "This review studies graph-based retrieval."), papers },
  { id: "demo-agents", name: "Reliable AI Agents", description: "Explore tool use, planning loops, evaluation, and recovery patterns.", accent: "from-cyan-500 to-blue-500", files: starterFiles("Reliable AI Agents", "This review studies evidence-grounded agents."), papers },
  { id: "demo-climate", name: "Climate Risk Modeling", description: "Preview an interdisciplinary review with connected evidence clusters.", accent: "from-emerald-500 to-teal-500", files: starterFiles("Climate Risk Modeling", "This review studies evidence synthesis for climate risk."), papers },
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
                papers,
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
