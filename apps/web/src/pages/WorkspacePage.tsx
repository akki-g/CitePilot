import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertCircle,
  BookOpen,
  Braces,
  Check,
  FileDown,
  MessageSquare,
  Network,
  PanelLeft,
  PanelRight,
  Save,
  X,
} from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { AgentPanel } from "@/components/agent/AgentPanel";
import { LatexEditor } from "@/components/editor/LatexEditor";
import { FileTree } from "@/components/editor/FileTree";
import { PdfPreview } from "@/components/editor/PdfPreview";
import { PaperSearchDialog } from "@/components/papers/PaperSearchDialog";
import { ProjectPaperList } from "@/components/papers/ProjectPaperList";
import { ApiError, listFiles, listProjectPapers, updateFile } from "@/lib/api";
import { refreshWorkspace } from "@/lib/refresh";
import type { Project, ProjectFile } from "@/lib/schemas";
import { useEditorStore } from "@/stores/editorStore";

const CitationGraph = lazy(() =>
  import("@/components/graph/CitationGraph").then((module) => ({
    default: module.CitationGraph,
  })),
);

type WorkspacePageProps = {
  project: Project;
  onBack: () => void;
  backIcon: LucideIcon;
};

function selectInitialFile(files: ProjectFile[]): ProjectFile | null {
  return files.find((file) => file.path === "main.tex") ?? files[0] ?? null;
}

export function WorkspacePage({ project, onBack, backIcon: BackIcon }: WorkspacePageProps) {
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [baseVersion, setBaseVersion] = useState(1);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"latex" | "pdf" | "graph">("latex");
  const [agentOpen, setAgentOpen] = useState(true);
  const [agentDock, setAgentDock] = useState<"left" | "right">("right");
  const [saveState, setSaveState] = useState<"idle" | "saved" | "error" | "conflict">("idle");
  // last server state adopted into the editor — lets refetches tell "the user
  // edited the draft" apart from "the file moved forward on the server"
  const syncRef = useRef<{ id: string; version: number; content: string } | null>(null);

  const selectedText = useEditorStore((state) => state.selectedText);
  const setSelectedText = useEditorStore((state) => state.setSelectedText);
  const setActiveFile = useEditorStore((state) => state.setActiveFile);

  const filesQuery = useQuery({
    queryKey: ["project-files", project.id],
    queryFn: () => listFiles(project.id),
  });
  const papersQuery = useQuery({
    queryKey: ["project-papers", project.id],
    queryFn: () => listProjectPapers(project.id),
    refetchInterval: 10_000,
  });

  const files = useMemo(() => filesQuery.data ?? [], [filesQuery.data]);
  const papers = useMemo(() => papersQuery.data ?? [], [papersQuery.data]);
  const graphablePapers = useMemo(
    () => papers.filter((paper) => !paper.is_stub && Boolean(paper.title?.trim())),
    [papers],
  );
  const activeFile = useMemo(
    () => files.find((file) => file.id === activeFileId) ?? null,
    [activeFileId, files],
  );
  const isDirty = activeFile ? draft !== activeFile.content || baseVersion !== activeFile.version : false;

  useEffect(() => {
    if (activeFileId || files.length === 0) {
      return;
    }
    const initial = selectInitialFile(files);
    if (initial) {
      setActiveFileId(initial.id);
    }
  }, [activeFileId, files]);

  // fix: this used to unconditionally reset the draft whenever the files query
  // refetched (agent turn done, import/compile finished), silently wiping
  // unsaved edits and disabling Save. Now server content is only adopted when
  // switching files, or when the server advanced and the draft is untouched.
  useEffect(() => {
    if (!activeFile) {
      return;
    }
    const synced = syncRef.current;
    const fileChanged = !synced || synced.id !== activeFile.id;
    const serverChanged =
      !fileChanged &&
      synced !== null &&
      (synced.version !== activeFile.version || synced.content !== activeFile.content);
    const userDirty = synced !== null && !fileChanged && draft !== synced.content;

    if (fileChanged || (serverChanged && !userDirty)) {
      syncRef.current = {
        id: activeFile.id,
        version: activeFile.version,
        content: activeFile.content,
      };
      setDraft(activeFile.content);
      setBaseVersion(activeFile.version);
      setActiveFile(activeFile.id, activeFile.path);
    }
    // serverChanged && userDirty: keep the local draft; Save will surface the
    // version conflict instead of silently discarding either side
  }, [activeFile, draft, setActiveFile]);

  // no auto-selection: the graph defaults to the whole-project overview, and
  // only a stale selection (paper removed) is cleared
  useEffect(() => {
    if (selectedPaperId && !graphablePapers.some((paper) => paper.paper_id === selectedPaperId)) {
      setSelectedPaperId(null);
    }
  }, [graphablePapers, selectedPaperId]);

  const saveMutation = useMutation({
    mutationFn: ({ content, explicit }: { content: string; explicit: boolean }) => {
      if (!activeFile) {
        throw new Error("No active file selected");
      }
      return updateFile(project.id, activeFile.id, {
        content,
        base_version: baseVersion,
        explicit,
      });
    },
    onSuccess: async (updated, variables) => {
      setSaveState("saved");
      setBaseVersion(updated.version);
      // adopt the saved content as the new sync point so the post-save
      // refetch is not mistaken for a remote change
      syncRef.current = { id: updated.id, version: updated.version, content: variables.content };
      await refreshWorkspace(project.id);
      window.setTimeout(() => setSaveState("idle"), 1800);
    },
    onError: (error) => {
      setSaveState(error instanceof ApiError && error.status === 409 ? "conflict" : "error");
    },
  });

  function switchFile(file: ProjectFile) {
    setActiveFileId(file.id);
    setSelectedText("");
    // the sync effect adopts the new file's content once activeFile resolves
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (activeFile && isDirty && !saveMutation.isPending) {
          saveMutation.mutate({ content: draft, explicit: true });
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeFile, isDirty, draft, saveMutation]);

  function insertCitation(bibtexKey: string) {
    const citation = `\\cite{${bibtexKey}}`;
    if (selectedText && draft.includes(selectedText)) {
      setDraft(draft.replace(selectedText, `${selectedText} ${citation}`));
      return;
    }
    setDraft(`${draft.trimEnd()}\n\n${citation}\n`);
  }

  const agentAside = agentOpen ? (
    <aside
      className={[
        "w-[400px] shrink-0 border-edge",
        agentDock === "left" ? "border-r" : "border-l",
        // below xl the panel floats over the editor instead of disappearing
        "max-xl:fixed max-xl:inset-y-0 max-xl:right-0 max-xl:z-40 max-xl:w-[min(400px,100vw)] max-xl:border-l max-xl:shadow-2xl max-xl:shadow-black/60",
      ].join(" ")}
    >
      <AgentPanel
        projectId={project.id}
        activeFilePath={activeFile?.path ?? null}
        selectedText={selectedText}
        onInsertCitation={insertCitation}
        onRefresh={() => refreshWorkspace(project.id)}
      />
    </aside>
  ) : null;

  const tabs = [
    { id: "latex" as const, label: "Editor", icon: Braces },
    { id: "pdf" as const, label: "PDF", icon: FileDown },
    { id: "graph" as const, label: "Graph", icon: Network },
  ];

  return (
    <main className="flex h-screen flex-col bg-ink-950 text-snow">
      <header className="z-20 shrink-0 border-b border-edge bg-ink-900">
        <div className="flex h-12 items-center justify-between gap-4 px-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <button
              type="button"
              className="grid h-8 w-8 place-items-center rounded-md text-fog hover:bg-ink-750 hover:text-mist"
              onClick={onBack}
              aria-label="Back to projects"
            >
              <BackIcon className="h-4 w-4" aria-hidden="true" />
            </button>
            <div className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
              <Braces className="h-3.5 w-3.5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold text-snow">{project.name}</h1>
            </div>
            <span className="hidden items-center gap-1 rounded border border-edge bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-fog sm:inline-flex">
              <BookOpen className="h-3 w-3" aria-hidden="true" />
              {papers.length} papers
            </span>
          </div>

          <nav className="flex items-center gap-1 rounded-lg border border-edge bg-ink-850 p-0.5">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  type="button"
                  className={[
                    "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition",
                    activeTab === tab.id
                      ? "bg-ink-700 text-snow shadow-sm"
                      : "text-fog hover:text-mist",
                  ].join(" ")}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  {tab.label}
                </button>
              );
            })}
          </nav>

          <div className="flex items-center gap-1.5">
            <div className="mr-1 hidden items-center text-[11px] sm:flex">
              {saveState === "saved" ? (
                <span className="inline-flex items-center gap-1 text-emerald-400">
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  Saved
                </span>
              ) : saveState === "conflict" ? (
                <span className="inline-flex items-center gap-1 text-red-400">
                  <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                  Version conflict — file changed elsewhere
                </span>
              ) : saveState === "error" ? (
                <span className="inline-flex items-center gap-1 text-red-400">
                  <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                  Save failed
                </span>
              ) : isDirty ? (
                <span className="text-amber-300">Unsaved changes</span>
              ) : null}
            </div>
            <button
              type="button"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-edge-2 bg-ink-800 px-2.5 text-xs font-medium text-mist hover:border-indigo-400/50 hover:text-indigo-200 disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => saveMutation.mutate({ content: draft, explicit: true })}
              disabled={!activeFile || saveMutation.isPending || !isDirty}
            >
              <Save className="h-3.5 w-3.5" aria-hidden="true" />
              Save
            </button>
            {agentOpen ? (
              <button
                type="button"
                className="hidden h-8 w-8 place-items-center rounded-md text-fog hover:bg-ink-750 hover:text-mist xl:grid"
                onClick={() => setAgentDock(agentDock === "right" ? "left" : "right")}
                aria-label={agentDock === "right" ? "Dock agent left" : "Dock agent right"}
                title={agentDock === "right" ? "Dock agent left" : "Dock agent right"}
              >
                {agentDock === "right" ? (
                  <PanelLeft className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <PanelRight className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            ) : null}
            <button
              type="button"
              className={[
                "inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition",
                agentOpen
                  ? "border border-edge-2 bg-ink-800 text-mist hover:text-snow"
                  : "bg-accent-deep text-white shadow-lg shadow-indigo-950/40 hover:bg-indigo-500",
              ].join(" ")}
              onClick={() => setAgentOpen((open) => !open)}
            >
              {agentOpen ? (
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              <span className="hidden lg:inline">{agentOpen ? "Hide agent" : "Agent"}</span>
            </button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {agentDock === "left" ? agentAside : null}

        <section className="flex min-w-0 flex-1 flex-col bg-ink-900">
          {activeTab === "latex" ? (
            <div className="flex min-h-0 flex-1">
              <aside className="flex w-60 shrink-0 flex-col border-r border-edge bg-ink-850 max-lg:hidden">
                <FileTree
                  projectId={project.id}
                  files={files}
                  activeFileId={activeFileId}
                  isLoading={filesQuery.isLoading}
                  onSelect={switchFile}
                  onImported={(imported) => {
                    const first = imported[0];
                    if (first) {
                      setActiveFileId(first.id);
                    }
                  }}
                />
                <div className="min-h-0 flex-1 overflow-y-auto border-t border-edge p-3">
                  <PaperSearchDialog projectId={project.id} />
                </div>
              </aside>
              <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex h-9 shrink-0 items-center justify-between border-b border-edge px-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-mono text-xs text-mist">
                      {activeFile?.path ?? "No file selected"}
                    </span>
                    {activeFile ? (
                      <span className="rounded border border-edge bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-fog">
                        v{baseVersion}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="min-h-0 flex-1">
                  <LatexEditor
                    value={draft}
                    path={activeFile?.path ?? ""}
                    onChange={setDraft}
                    onSelectionChange={setSelectedText}
                  />
                </div>
              </div>
            </div>
          ) : null}

          {activeTab === "pdf" ? (
            <div className="min-h-0 flex-1 p-3">
              <PdfPreview projectId={project.id} mode="full" />
            </div>
          ) : null}

          {activeTab === "graph" ? (
            <div className="flex min-h-0 flex-1 gap-3 p-3">
              <aside className="flex w-80 shrink-0 flex-col gap-3 max-lg:hidden">
                <div className="shrink-0 rounded-xl border border-edge bg-ink-850 p-3">
                  <PaperSearchDialog projectId={project.id} compact />
                </div>
                <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-edge bg-ink-850">
                  <ProjectPaperList
                    papers={graphablePapers}
                    isLoading={papersQuery.isLoading}
                    selectedPaperId={selectedPaperId}
                    onSelectPaper={(paperId) =>
                      // clicking the selected paper again returns to the overview
                      setSelectedPaperId((current) => (current === paperId ? null : paperId))
                    }
                  />
                </div>
              </aside>
              <div className="min-w-0 flex-1">
                <Suspense
                  fallback={
                    <div className="grid h-full min-h-[480px] place-items-center rounded-xl border border-edge bg-ink-900 text-xs text-fog">
                      Loading citation graph...
                    </div>
                  }
                >
                  <CitationGraph
                    projectId={project.id}
                    paperId={selectedPaperId}
                    onSelectPaper={setSelectedPaperId}
                    mode="full"
                  />
                </Suspense>
              </div>
            </div>
          ) : null}
        </section>

        {agentDock === "right" ? agentAside : null}
      </div>
    </main>
  );
}
