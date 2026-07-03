import { Activity, Braces, Database, Network } from "lucide-react";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const workspacePanels = [
  { title: "LaTeX Editor", detail: "CodeMirror workspace shell", icon: Braces },
  { title: "Research Agent", detail: "Tool traces and citation suggestions", icon: Activity },
  { title: "Knowledge Graph", detail: "Neo4j neighborhoods and retrieval signals", icon: Network },
  { title: "Backend API", detail: apiBaseUrl, icon: Database },
];

export default function App() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <section className="mx-auto flex min-h-screen w-full max-w-6xl flex-col justify-center px-6 py-12">
        <div className="max-w-2xl">
          <p className="text-sm font-medium uppercase tracking-[0.24em] text-cyan-300">
            CitePilot
          </p>
          <h1 className="mt-4 text-4xl font-semibold tracking-normal text-white sm:text-5xl">
            Vite React workspace ready for the backend proof of concept.
          </h1>
          <p className="mt-5 text-base leading-7 text-zinc-300">
            The frontend is intentionally lightweight: React, TypeScript, Tailwind,
            TanStack Query, Zustand-ready dependencies, and a Vite dev server bound
            to port 3000 for Docker Compose.
          </p>
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {workspacePanels.map((panel) => {
            const Icon = panel.icon;
            return (
              <div key={panel.title} className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
                <Icon className="h-5 w-5 text-cyan-300" aria-hidden="true" />
                <h2 className="mt-4 text-base font-semibold text-white">{panel.title}</h2>
                <p className="mt-2 text-sm leading-6 text-zinc-400">{panel.detail}</p>
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}
