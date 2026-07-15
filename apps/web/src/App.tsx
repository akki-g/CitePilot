import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Braces,
  FileText,
  LogIn,
  LogOut,
  Network,
  PlayCircle,
  Plus,
  Search,
  Sparkles,
} from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { AuthPage } from "@/pages/AuthPage";
import {
  createProject,
  getAuthProviders,
  getCurrentUser,
  getHealth,
  listProjects,
  logout,
  verifyEmail,
} from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import { useEditorStore } from "@/stores/editorStore";
import type { AuthUser, Project } from "@/lib/schemas";

const WorkspacePage = lazy(() =>
  import("@/pages/WorkspacePage").then((module) => ({ default: module.WorkspacePage })),
);
const DemoPage = lazy(() =>
  import("@/pages/DemoPage").then((module) => ({ default: module.DemoPage })),
);

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

function ProjectListPage({
  user,
  onOpen,
  onDemo,
  onLogout,
}: {
  user: AuthUser;
  onOpen: (project: Project) => void;
  onDemo: () => void;
  onLogout: () => void;
}) {
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
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px]"
        style={{
          background:
            "radial-gradient(600px 260px at 30% 0%, rgba(49,87,213,0.08), transparent), radial-gradient(500px 240px at 75% 10%, rgba(34,123,118,0.05), transparent)",
        }}
      />

      <header className="relative border-b border-edge bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm">
              <Braces className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-snow">CitePilot</h1>
              <p className="text-xs text-fog">Citation-aware LaTeX writing, powered by GraphRAG</p>
            </div>
          </div>
          <div className="hidden items-center gap-2 lg:flex">
            <StatusPill label="api" value={healthQuery.data?.status} />
            <StatusPill label="postgres" value={healthQuery.data?.postgres} />
            <StatusPill label="neo4j" value={healthQuery.data?.neo4j} />
            <StatusPill label="redis" value={healthQuery.data?.redis} />
            <span className="ml-2 h-6 w-px bg-edge" />
            <button onClick={onDemo} className="rounded-lg px-2 py-1.5 text-xs text-fog hover:bg-ink-800 hover:text-snow">Demo</button>
            <span className="max-w-32 truncate text-xs text-mist">{user.display_name || user.email}</span>
            <button onClick={onLogout} title="Sign out" className="rounded-lg p-2 text-fog hover:bg-ink-800 hover:text-snow"><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
      </header>

      <section className="relative mx-auto max-w-6xl px-6 pb-16 pt-10">
        <div className="max-w-2xl">
          <h2 className="text-3xl font-bold leading-tight tracking-tight text-snow">
            Write papers with an agent that <span className="text-indigo-300">knows the literature</span>.
          </h2>
          <p className="mt-3 text-sm leading-6 text-fog">
            Search and import scholarly work, explore citation neighborhoods, and let the agent
            ground every suggestion in retrieved evidence — straight into your LaTeX draft.
          </p>
        </div>

        <div className="mt-10 grid gap-6 lg:grid-cols-[340px_1fr]">
          <form
            className="h-fit rounded-xl border border-edge bg-ink-900/90 p-5 shadow-sm"
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
            <label className="mt-4 block text-[11px] font-semibold uppercase tracking-wide text-fog" htmlFor="description">
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
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-deep px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
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
                Projects <span className="ml-2 font-mono text-xs text-fog">{projects.length}</span>
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
                  className="group rounded-xl border border-edge bg-ink-900/90 p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-400/40 hover:bg-ink-850"
                  onClick={() => {
                    setActiveProject(project.id);
                    onOpen(project);
                  }}
                >
                  <div className="flex items-start justify-between">
                    <FileText className="h-5 w-5 text-indigo-300" aria-hidden="true" />
                    <ArrowUpRight className="h-4 w-4 text-fog opacity-0 transition group-hover:opacity-100" aria-hidden="true" />
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
            { icon: Sparkles, title: "Streaming agent", text: "Watch tool calls and evidence stream in as the agent researches for you." },
            { icon: Network, title: "Citation graph", text: "Explore who cites whom, with abstracts and BibTeX one click away." },
            { icon: Braces, title: "LaTeX-native", text: "Versioned files, reviewed patches, and one-click Tectonic compiles." },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.title} className="rounded-xl border border-edge bg-ink-900/70 p-4">
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

function LandingPage({ onDemo, onLogin }: { onDemo: () => void; onLogin: () => void }) {
  return (
    <main className="min-h-screen overflow-hidden bg-ink-950">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[620px] bg-[radial-gradient(700px_380px_at_50%_0%,rgba(49,87,213,.10),transparent),radial-gradient(500px_300px_at_80%_20%,rgba(34,123,118,.06),transparent)]" />
      <header className="relative mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-accent-deep text-white"><Braces className="h-4 w-4" /></div>
          <span className="font-bold text-snow">CitePilot</span>
        </div>
        <button onClick={onLogin} className="flex items-center gap-2 rounded-lg border border-edge-2 bg-ink-900 px-4 py-2 text-xs font-semibold text-mist shadow-sm hover:border-indigo-400/50 hover:text-snow"><LogIn className="h-3.5 w-3.5" /> Sign in</button>
      </header>
      <section className="relative mx-auto max-w-6xl px-6 pb-20 pt-20 text-center">
        <span className="rounded-full border border-indigo-400/25 bg-indigo-400/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-widest text-indigo-200">Agentic research workspace</span>
        <h1 className="mx-auto mt-6 max-w-4xl text-4xl font-bold leading-tight tracking-tight text-snow sm:text-6xl">
          Write with an AI agent that can <span className="text-indigo-300">trace the evidence.</span>
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-sm leading-7 text-fog sm:text-base">
          CitePilot combines a LaTeX editor, a scientific citation graph, and grounded research agents in one project workspace.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <button onClick={onDemo} className="flex items-center gap-2 rounded-lg bg-accent-deep px-5 py-3 text-sm font-semibold text-white shadow-md hover:bg-indigo-500"><PlayCircle className="h-4 w-4" /> Try the no-login demo</button>
          <button onClick={onLogin} className="rounded-lg border border-edge-2 bg-ink-900 px-5 py-3 text-sm font-semibold text-mist shadow-sm hover:border-indigo-400/50 hover:text-snow">Create a private workspace</button>
        </div>
        <p className="mt-4 text-[10px] text-fog">The demo is ephemeral. Accounts save private projects for later.</p>
        <div className="mt-16 grid gap-4 text-left md:grid-cols-3">
          {[
            { icon: Network, title: "Understand the graph", text: "See project papers, shared foundations, and citation paths with readable context." },
            { icon: Sparkles, title: "Work with grounded agents", text: "Stream research, evidence, and reviewable LaTeX patches into your draft." },
            { icon: FileText, title: "Keep a durable workspace", text: "Return to your files, bibliography, graph, and latest compiled PDF whenever you sign in." },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.title} className="rounded-xl border border-edge bg-ink-900/80 p-5 shadow-sm">
                <Icon className="h-5 w-5 text-indigo-300" />
                <h2 className="mt-4 text-sm font-semibold text-snow">{item.title}</h2>
                <p className="mt-2 text-xs leading-5 text-fog">{item.text}</p>
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}

function VerificationPage({ token, onVerified }: { token: string; onVerified: (user: AuthUser) => void }) {
  const mutation = useMutation({ mutationFn: verifyEmail, onSuccess: onVerified });
  const mutate = mutation.mutate;
  const attempted = useRef(false);
  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;
    mutate(token);
  }, [mutate, token]);
  return <main className="grid min-h-screen place-items-center bg-ink-950 px-5"><div className="w-full max-w-md rounded-xl border border-edge bg-ink-900 p-7 text-center"><Sparkles className="mx-auto h-7 w-7 text-indigo-300" /><h1 className="mt-4 text-lg font-semibold text-snow">{mutation.isPending ? "Verifying your email…" : mutation.isError ? "That link did not work" : "Email verified"}</h1><p className={`mt-2 text-xs leading-5 ${mutation.isError ? "text-red-300" : "text-fog"}`}>{mutation.isError ? mutation.error.message : "Setting up your secure workspace."}</p></div></main>;
}

export default function App() {
  const initialParams = new URLSearchParams(window.location.search);
  const fragmentParams = new URLSearchParams(window.location.hash.slice(1));
  const verificationToken = fragmentParams.get("verify") ?? initialParams.get("verify");
  const oauthError = initialParams.get("auth_error");
  const [screen, setScreen] = useState<"landing" | "auth" | "demo">(
    initialParams.get("demo") === "1" ? "demo" : initialParams.has("auth_error") ? "auth" : "landing",
  );
  const [openProject, setOpenProject] = useState<Project | null>(null);
  const setActiveProject = useEditorStore((state) => state.setActiveProject);
  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
    retry: false,
    staleTime: 60_000,
    enabled: screen !== "demo" && !verificationToken,
  });
  const providersQuery = useQuery({
    queryKey: ["auth", "providers"],
    queryFn: getAuthProviders,
    enabled: screen === "auth",
    staleTime: 300_000,
  });
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      setOpenProject(null);
      setActiveProject(null);
      setScreen("landing");
    },
  });

  useEffect(() => {
    setActiveProject(openProject?.id ?? null);
  }, [openProject?.id, setActiveProject]);

  const acceptUser = (user: AuthUser) => {
    queryClient.setQueryData(["auth", "me"], user);
    window.history.replaceState({}, "", window.location.pathname);
    setScreen("landing");
  };

  if (verificationToken) {
    return <VerificationPage token={verificationToken} onVerified={acceptUser} />;
  }

  if (screen === "demo") {
    return <Suspense fallback={<main className="grid min-h-screen place-items-center bg-ink-950 text-sm text-fog">Opening demo…</main>}><DemoPage onExit={() => setScreen("landing")} onSignUp={() => setScreen("auth")} /></Suspense>;
  }

  if (meQuery.isLoading) {
    return <main className="grid min-h-screen place-items-center bg-ink-950"><div className="flex items-center gap-3 text-sm text-fog"><Braces className="h-5 w-5 animate-pulse text-indigo-300" /> Loading CitePilot…</div></main>;
  }

  if (!meQuery.data && screen === "auth") {
    return <AuthPage providers={providersQuery.data} oauthError={oauthError} onAuthenticated={acceptUser} onBack={() => setScreen("landing")} />;
  }

  if (meQuery.data && openProject) {
    return (
      <Suspense fallback={<main className="grid min-h-screen place-items-center bg-ink-950 text-sm text-fog">Opening workspace…</main>}>
        <WorkspacePage
          project={openProject}
          onBack={() => {
            setOpenProject(null);
            setActiveProject(null);
          }}
          backIcon={ArrowLeft}
        />
      </Suspense>
    );
  }

  if (meQuery.data) {
    return <ProjectListPage user={meQuery.data} onOpen={setOpenProject} onDemo={() => setScreen("demo")} onLogout={() => logoutMutation.mutate()} />;
  }

  return <LandingPage onDemo={() => setScreen("demo")} onLogin={() => setScreen("auth")} />;
}
