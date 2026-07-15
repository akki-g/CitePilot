import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileDown, Loader2, RefreshCw } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  compileLatex,
  getCompilation,
  getLatestCompilation,
  getPdfUrl,
} from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import { refreshWorkspace } from "@/lib/refresh";

function formatCompiledAt(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function PdfPreview({
  projectId,
  mode = "compact",
  hasUnsavedChanges = false,
  onBeforeCompile,
}: {
  projectId: string;
  mode?: "compact" | "full";
  hasUnsavedChanges?: boolean;
  onBeforeCompile?: () => Promise<void>;
}) {
  const [compilationId, setCompilationId] = useState<string | null>(null);
  const completedCompilation = useRef<string | null>(null);

  const latestQuery = useQuery({
    queryKey: ["latest-compilation", projectId],
    queryFn: () => getLatestCompilation(projectId),
    staleTime: 15_000,
  });

  const compileMutation = useMutation({
    mutationFn: async () => {
      await onBeforeCompile?.();
      return compileLatex(projectId);
    },
    onSuccess: (result) => setCompilationId(result.compilation_id),
  });

  const compilationQuery = useQuery({
    queryKey: ["compilation", compilationId],
    queryFn: () => getCompilation(compilationId ?? ""),
    enabled: Boolean(compilationId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1500 : false;
    },
  });

  // If the user leaves the PDF tab during a compile, the durable latest-attempt
  // endpoint lets the preview resume polling when they return.
  useEffect(() => {
    const attempt = latestQuery.data?.latest_attempt;
    if (
      attempt &&
      (attempt.status === "queued" || attempt.status === "running") &&
      attempt.id !== compilationId
    ) {
      setCompilationId(attempt.id);
    }
  }, [compilationId, latestQuery.data?.latest_attempt]);

  const activeCompilation = compilationQuery.data;
  const activeStatus = activeCompilation?.status;

  useEffect(() => {
    if (
      compilationId &&
      activeStatus &&
      (activeStatus === "completed" || activeStatus === "failed") &&
      completedCompilation.current !== compilationId
    ) {
      completedCompilation.current = compilationId;
      void queryClient.invalidateQueries({ queryKey: ["latest-compilation", projectId] });
      void refreshWorkspace(projectId);
    }
  }, [activeStatus, compilationId, projectId]);

  const latestSuccessful = latestQuery.data?.compilation ?? null;
  const displayedCompilation =
    activeCompilation?.status === "completed" && activeCompilation.has_pdf
      ? activeCompilation
      : latestSuccessful;
  const latestAttempt = activeCompilation ?? latestQuery.data?.latest_attempt ?? null;
  const failure = latestAttempt?.status === "failed" ? latestAttempt : null;
  const requestError = compileMutation.error;
  const effectiveStatus = activeStatus ?? latestQuery.data?.latest_attempt?.status;
  const inFlight =
    compileMutation.isPending || effectiveStatus === "queued" || effectiveStatus === "running";
  const isStale =
    hasUnsavedChanges ||
    (activeCompilation?.status === "completed" ? false : latestQuery.data?.is_stale);
  const compiledAt = formatCompiledAt(displayedCompilation?.completed_at);

  return (
    <section
      className={[
        "flex min-h-0 flex-col overflow-hidden",
        mode === "full" ? "h-full rounded-xl border border-edge bg-ink-900" : "border-t border-edge",
      ].join(" ")}
    >
      <div className="flex min-h-11 shrink-0 items-center justify-between gap-3 border-b border-edge px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <FileDown className="h-4 w-4 shrink-0 text-indigo-300" aria-hidden="true" />
          <h2 className="shrink-0 text-xs font-semibold uppercase tracking-wide text-mist">
            PDF preview
          </h2>
          {compiledAt ? (
            <span className="hidden truncate font-mono text-[10px] text-fog sm:inline">
              Last compiled {compiledAt}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {failure || requestError ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-red-400">
              <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
              Refresh failed
            </span>
          ) : isStale && displayedCompilation ? (
            <span className="text-[11px] font-medium text-amber-300">Changes pending</span>
          ) : displayedCompilation ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-label="PDF is current" />
          ) : null}
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-edge-2 bg-ink-800 px-2.5 py-1 text-xs font-medium text-mist hover:border-indigo-400/50 hover:text-indigo-200 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => compileMutation.mutate()}
            disabled={inFlight}
          >
            {inFlight ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {inFlight ? "Refreshing..." : displayedCompilation ? "Refresh PDF" : "Build PDF"}
          </button>
        </div>
      </div>

      <div
        className={[
          "flex min-h-0 flex-1 flex-col bg-ink-950",
          mode === "compact" ? "h-64" : "",
        ].join(" ")}
      >
        {failure || requestError ? (
          <details className="shrink-0 border-b border-red-400/20 bg-red-400/5 px-3 py-2 text-xs text-red-300">
            <summary className="cursor-pointer font-medium">
              {failure?.error ?? requestError?.message ?? "The latest PDF refresh failed"}.
              {displayedCompilation ? " The previous PDF is still shown." : ""}
            </summary>
            {failure?.logs ? (
              <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap rounded border border-edge bg-ink-900 p-2 font-mono text-[10px] leading-4 text-fog">
                {failure.logs}
              </pre>
            ) : null}
          </details>
        ) : null}

        {displayedCompilation?.has_pdf ? (
          <iframe
            key={displayedCompilation.id}
            className="min-h-0 w-full flex-1 border-0 bg-white"
            title="Last compiled PDF"
            src={getPdfUrl(displayedCompilation.id)}
          />
        ) : latestQuery.isLoading ? (
          <div className="grid h-full place-items-center">
            <Loader2 className="h-5 w-5 animate-spin text-fog" aria-hidden="true" />
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <FileDown className="h-6 w-6 text-fog" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium text-mist">
              {inFlight ? "Building the first PDF..." : "No PDF compiled yet"}
            </p>
            <p className="mt-1 max-w-md text-xs leading-5 text-fog">
              Build the PDF once; afterward this tab will always reopen the latest successful
              version.
            </p>
            {latestQuery.error ? (
              <p className="mt-2 text-xs text-red-300">{latestQuery.error.message}</p>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
