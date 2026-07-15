import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Download, Loader2, Search } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { getJob, importPaper, searchPapers } from "@/lib/api";
import { refreshWorkspace } from "@/lib/refresh";
import type { PaperSearchResult } from "@/lib/schemas";

function ImportJobRow({
  jobId,
  projectId,
  title,
}: {
  jobId: string;
  projectId: string;
  title: string;
}) {
  const completedJob = useRef<string | null>(null);
  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    },
  });

  const job = jobQuery.data;
  const status = job?.status;

  useEffect(() => {
    if (status && ["completed", "failed"].includes(status) && completedJob.current !== jobId) {
      completedJob.current = jobId;
      void refreshWorkspace(projectId);
    }
  }, [jobId, status, projectId]);

  return (
    <div className="rounded-md border border-edge bg-ink-800 px-2.5 py-1.5 text-xs text-fog">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate" title={title}>
          {title} · {job?.status ?? "queued"}
        </span>
        {job?.status === "completed" ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
        ) : job?.status === "failed" ? (
          <span className="text-[10px] font-medium text-red-400">failed</span>
        ) : (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-fog" aria-hidden="true" />
        )}
      </div>
      {job?.error ? <p className="mt-1 text-red-400">{job.error}</p> : null}
    </div>
  );
}

function SearchResultCard({
  paper,
  onImport,
  isImporting,
}: {
  paper: PaperSearchResult;
  onImport: (paper: PaperSearchResult) => void;
  isImporting: boolean;
}) {
  const canImport = Boolean(paper.external_id) && !paper.imported;

  return (
    <article className="rounded-lg border border-edge bg-ink-800 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="line-clamp-2 text-xs font-semibold leading-4 text-snow">
            {paper.title ?? "Untitled paper"}
          </h4>
          <p className="mt-1 text-[11px] leading-4 text-fog">
            {paper.authors.slice(0, 3).join(", ") || "Unknown authors"} · {paper.year ?? "n.d."} ·{" "}
            {paper.cited_by_count.toLocaleString()} cites
          </p>
        </div>
        <button
          type="button"
          className={[
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-1 text-[10px] font-medium",
            paper.imported
              ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
              : "border-edge-2 bg-ink-750 text-mist hover:border-indigo-400/50 hover:text-indigo-200",
            "disabled:cursor-not-allowed disabled:opacity-50",
          ].join(" ")}
          disabled={!canImport || isImporting}
          onClick={() => onImport(paper)}
        >
          {isImporting ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          ) : paper.imported ? (
            <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
          ) : (
            <Download className="h-3 w-3" aria-hidden="true" />
          )}
          {paper.imported ? "In project" : "Import"}
        </button>
      </div>
      {paper.abstract ? (
        <p className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-fog">{paper.abstract}</p>
      ) : null}
    </article>
  );
}

export function PaperSearchDialog({
  projectId,
  compact = false,
}: {
  projectId: string;
  compact?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [source, setSource] = useState<"openalex" | "local">("openalex");
  const [jobs, setJobs] = useState<Array<{ id: string; title: string }>>([]);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setDebouncedQuery("");
      return;
    }
    const timer = window.setTimeout(() => setDebouncedQuery(trimmed), 450);
    return () => window.clearTimeout(timer);
  }, [query]);

  const searchQuery = useQuery({
    queryKey: ["paper-search", projectId, source, debouncedQuery],
    queryFn: () =>
      searchPapers({ query: debouncedQuery, source, project_id: projectId, limit: 8 }),
    enabled: debouncedQuery.length >= 2,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });
  const importMutation = useMutation({
    mutationFn: (paper: PaperSearchResult) =>
      importPaper({
        source: "openalex",
        source_id: paper.external_id ?? "",
        project_id: projectId,
      }),
    onSuccess: (result, paper) => {
      setJobs((current) => [
        { id: result.job_id, title: paper.title ?? "Untitled paper" },
        ...current,
      ].slice(0, 4));
    },
  });

  const results = useMemo(() => searchQuery.data?.papers ?? [], [searchQuery.data?.papers]);

  return (
    <section>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Search className="h-3.5 w-3.5 text-indigo-300" aria-hidden="true" />
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fog">
            Paper search
          </h2>
        </div>
        <select
          className="rounded-md border border-edge-2 bg-ink-800 px-1.5 py-0.5 text-[11px] text-mist outline-none focus:border-indigo-400/60"
          value={source}
          onChange={(event) => setSource(event.target.value as "openalex" | "local")}
          aria-label="Search source"
        >
          <option value="openalex">OpenAlex</option>
          <option value="local">Local</option>
        </select>
      </div>
      <form
        className="mt-2 flex items-center gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) {
            setDebouncedQuery(query.trim());
          }
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-md border border-edge-2 bg-ink-800 px-2.5 py-1.5 text-xs text-snow outline-none transition placeholder:text-fog focus:border-indigo-400/60"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Title, DOI, author, or OpenAlex ID..."
        />
        <button
          type="submit"
          className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-accent-deep text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={searchQuery.isFetching || !query.trim()}
          aria-label="Search"
        >
          {searchQuery.isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      </form>

      {searchQuery.error ? (
        <p className="mt-2 rounded-md border border-red-400/25 bg-red-400/5 px-2.5 py-1.5 text-xs text-red-300">
          {searchQuery.error.message}
        </p>
      ) : null}

      {jobs.length > 0 ? (
        <div className="mt-2 space-y-1.5">
          {jobs.map((job) => (
            <ImportJobRow key={job.id} jobId={job.id} projectId={projectId} title={job.title} />
          ))}
        </div>
      ) : null}

      {results.length > 0 ? (
        <div className={["mt-2 space-y-1.5 overflow-y-auto", compact ? "max-h-64" : "max-h-96"].join(" ")}>
          {results.map((paper) => (
            <SearchResultCard
              key={paper.external_id ?? paper.paper_id ?? paper.title}
              paper={paper}
              onImport={(selected) => importMutation.mutate(selected)}
              isImporting={
                importMutation.isPending && importMutation.variables?.external_id === paper.external_id
              }
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
