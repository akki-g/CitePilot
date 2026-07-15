import { BookOpen, Loader2 } from "lucide-react";

import type { ProjectPaper } from "@/lib/schemas";

type ProjectPaperListProps = {
  papers: ProjectPaper[];
  isLoading: boolean;
  selectedPaperId: string | null;
  onSelectPaper: (paperId: string) => void;
};

export function ProjectPaperList({
  papers,
  isLoading,
  selectedPaperId,
  onSelectPaper,
}: ProjectPaperListProps) {
  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-edge px-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-3.5 w-3.5 text-indigo-300" aria-hidden="true" />
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fog">
            Bibliography
          </h2>
          <span className="font-mono text-[10px] text-fog">{papers.length}</span>
        </div>
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-fog" aria-hidden="true" />
        ) : null}
      </div>
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-2.5">
        {papers.map((paper) => {
          const active = paper.paper_id === selectedPaperId;
          return (
            <button
              key={paper.paper_id}
              type="button"
              className={[
                "w-full rounded-lg border p-2.5 text-left transition",
                active
                  ? "border-indigo-400/50 bg-indigo-500/10"
                  : "border-edge bg-ink-800 hover:border-edge-2 hover:bg-ink-750",
              ].join(" ")}
              onClick={() => onSelectPaper(paper.paper_id)}
            >
              <p
                className={[
                  "line-clamp-2 text-xs font-medium leading-4",
                  active ? "text-indigo-100" : "text-snow",
                ].join(" ")}
              >
                {paper.title ?? paper.bibtex_key}
              </p>
              <p className="mt-1 font-mono text-[10px] text-fog">
                {paper.bibtex_key} · {paper.year ?? "n.d."} ·{" "}
                {paper.cited_by_count.toLocaleString()} cites
              </p>
            </button>
          );
        })}
        {!isLoading && papers.length === 0 ? (
          <p className="rounded-lg border border-dashed border-edge-2 p-4 text-xs leading-5 text-fog">
            Search and import papers to populate this project bibliography.
          </p>
        ) : null}
      </div>
    </section>
  );
}
