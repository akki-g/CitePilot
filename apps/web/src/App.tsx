import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Braces,
  FileText,
  Network,
  Plus,
  Search,
  Sparkles,
} from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { WorkspacePage } from "@/pages/WorkspacePage";
import { createProject, getHealth, listProjects } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import { useEditorStore } from "@/stores/editorStore";
import type { Project } from "@/lib/schemas";

function StatusPill({ label, value }: { label: string; value?: string }) {
  const ok = value === "ok" || value === "healthy";
  const degraded = value === "degraded" || value === "error";

  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] font-medium",
        ok
          ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-300"
          : degraded
            ? "border-amber-400/25 bg-amber-400/10 text-amber-300"
            : "border-edge-2 bg-ink-800 text-fog",
      ].join(" ")}
    >
      <span className={["h-1.5 w-1.5 rounded-full bg-current", ok ? "animate-pulse" : ""].join(" ")} />
      {label}
    </span>
  );
}

function ProjectListPage({ onOpen }: { onOpen: (project: Project) => void }) {
  const [name, setName] = useState("GraphRAG Literature Review");
  const [description, setDescription] = useState("Citation-aware related work draft");
  const [filter, setFilter] = useState("");
  const setActiveProject = useEditorStore((state) => state.setActiveProject);

  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 15_000 });

  const createMutation = useMutation({
    mutationFn: createProject,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      setActiveProject(project.id);
      onOpen(project);
    },
  });

  const projects = (projectsQuery.data ?? []).filter((project) =>
    project.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <main className="min-h-screen bg-ink-950">
      {/* ambient glow behind the hero */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px]"
        style={{
          background:
            "radial-gradient(600px 260px at 30% 0%, rgba(99,102,241,0.16), transparent), radial-gradient(500px 240px at 75% 10%, rgba(34,211,238,0.08), transparent)",
        }}
      />

      <header className="relative border-b border-edge">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-950/50">
              <Braces className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-snow">CitePilot</h1>
              <p className="text-xs text-fog">Citation-aware LaTeX writing, powered by GraphRAG</p>
            </div>
          </div>
          <div className="hidden items-center gap-2 md:flex">
            <StatusPill label="api" value={healthQuery.data?.status} />
            <StatusPill label="postgres" value={healthQuery.data?.postgres} />
            <StatusPill label="neo4j" value={healthQuery.data?.neo4j} />
            <StatusPill label="redis" value={healthQuery.data?.redis} />
          </div>
        </div>
      </header>

      <section className="relative mx-auto max-w-6xl px-6 pb-16 pt-10">
        <div className="max-w-2xl">
          <h2 className="text-3xl font-bold leading-tight tracking-tight text-snow">
            Write papers with an agent that
            <span className="bg-gradient-to-r from-indigo-300 via-violet-300 to-cyan-300 bg-clip-text text-transparent">
              {" "}
              knows the literature
            </span>
            .
          </h2>
          <p className="mt-3 text-sm leading-6 text-fog">
            Search and import scholarly work, explore citation neighborhoods, and let the agent
            ground every suggestion in retrieved evidence — straight into your LaTeX draft.
          </p>
        </div>

        <div className="mt-10 grid gap-6 lg:grid-cols-[340px_1fr]">
          <form
            className="h-fit rounded-xl border border-edge bg-ink-900/80 p-5 backdrop-blur"
            onSubmit={(event) => {
              event.preventDefault();
              createMutation.mutate({ name, description });
            }}
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-snow">
              <Plus className="h-4 w-4 text-indigo-300" aria-hidden="true" />
              New project
            </div>
            <label className="mt-4 block text-[11px] font-semibold uppercase tracking-wide text-fog" htmlFor="name">
              Project name
            </label>
            <input
              id="name"
              className="mt-1.5 w-full rounded-lg border border-edge-2 bg-ink-800 px-3 py-2 text-sm text-snow outline-none transition placeholder:text-fog focus:border-indigo-400/60"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <label
              className="mt-4 block text-[11px] font-semibold uppercase tracking-wide text-fog"
              htmlFor="description"
            >
              Description
            </label>
            <textarea
              id="description"
              className="mt-1.5 min-h-20 w-full resize-none rounded-lg border border-edge-2 bg-ink-800 px-3 py-2 text-sm text-snow outline-none transition placeholder:text-fog focus:border-indigo-400/60"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <button
              type="submit"
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-deep px-3 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-950/40 transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={createMutation.isPending || !name.trim()}
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              {createMutation.isPending ? "Creating..." : "Create workspace"}
            </button>
            {createMutation.error ? (
              <p className="mt-3 rounded-lg border border-red-400/25 bg-red-400/5 px-3 py-2 text-xs text-red-300">
                {createMutation.error.message}
              </p>
            ) : null}
          </form>

          <div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-sm font-semibold text-snow">
                Projects
                <span className="ml-2 font-mono text-xs text-fog">{projects.length}</span>
              </h3>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-fog" />
                <input
                  className="w-full rounded-lg border border-edge-2 bg-ink-800 py-2 pl-9 pr-3 text-xs text-snow outline-none transition placeholder:text-fog focus:border-indigo-400/60 sm:w-64"
                  placeholder="Filter projects"
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                />
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  className="group rounded-xl border border-edge bg-ink-900/80 p-4 text-left transition hover:border-indigo-400/40 hover:bg-ink-850"
                  onClick={() => {
                    setActiveProject(project.id);
                    onOpen(project);
                  }}
                >
                  <div className="flex items-start justify-between">
                    <FileText className="h-5 w-5 text-indigo-300" aria-hidden="true" />
                    <ArrowUpRight
                      className="h-4 w-4 text-fog opacity-0 transition group-hover:opacity-100"
                      aria-hidden="true"
                    />
                  </div>
                  <h4 className="mt-3 text-sm font-semibold text-snow">{project.name}</h4>
                  <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-fog">
                    {project.description ?? "LaTeX project with main.tex and references.bib"}
                  </p>
                </button>
              ))}
              {!projectsQuery.isLoading && projects.length === 0 ? (
                <div className="col-span-full rounded-xl border border-dashed border-edge-2 p-10 text-center">
                  <BookOpen className="mx-auto h-6 w-6 text-fog" aria-hidden="true" />
                  <p className="mt-3 text-sm font-medium text-mist">No projects yet</p>
                  <p className="mt-1 text-xs text-fog">Create one to open the writing workspace.</p>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="mt-14 grid gap-3 md:grid-cols-3">
          {[
            {
              icon: Sparkles,
              title: "Streaming agent",
              text: "Watch tool calls and evidence stream in as the agent researches for you.",
            },
            {
              icon: Network,
              title: "Citation graph",
              text: "Explore who cites whom, with abstracts and BibTeX one click away.",
            },
            {
              icon: Braces,
              title: "LaTeX-native",
              text: "Versioned files, reviewed patches, and one-click Tectonic compiles.",
            },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.title} className="rounded-xl border border-edge bg-ink-900/60 p-4">
                <Icon className="h-4 w-4 text-indigo-300" aria-hidden="true" />
                <h3 className="mt-3 text-sm font-semibold text-snow">{item.title}</h3>
                <p className="mt-1 text-xs leading-5 text-fog">{item.text}</p>
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}

export default function App() {
  const [openProject, setOpenProject] = useState<Project | null>(null);
  const setActiveProject = useEditorStore((state) => state.setActiveProject);

  useEffect(() => {
    setActiveProject(openProject?.id ?? null);
  }, [openProject?.id, setActiveProject]);

  if (openProject) {
    return (
      <WorkspacePage
        project={openProject}
        onBack={() => {
          setOpenProject(null);
          setActiveProject(null);
        }}
        backIcon={ArrowLeft}
      />
    );
  }

  return <ProjectListPage onOpen={setOpenProject} />;
}
