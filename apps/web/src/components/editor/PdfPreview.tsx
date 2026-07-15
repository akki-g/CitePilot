import { useEffect, useRef, useState } from "react";
import { CheckCircle2, FileDown, Loader2, Play } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { compileLatex, getCompilation, getPdfUrl } from "@/lib/api";
import { refreshWorkspace } from "@/lib/refresh";

export function PdfPreview({
  projectId,
  mode = "compact",
}: {
  projectId: string;
  mode?: "compact" | "full";
}) {
  const [compilationId, setCompilationId] = useState<string | null>(null);
  const completedCompilation = useRef<string | null>(null);
  const compileMutation = useMutation({
    mutationFn: () => compileLatex(projectId),
    onSuccess: (result) => setCompilationId(result.compilation_id),
  });

  const compilationQuery = useQuery({
    queryKey: ["compilation", compilationId],
    queryFn: () => getCompilation(compilationId ?? ""),
    enabled: Boolean(compilationId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2500 : false;
    },
  });

  const compilation = compilationQuery.data;
  const status = compilation?.status;
  const inFlight =
    compileMutation.isPending || status === "queued" || status === "running";

  useEffect(() => {
    if (
      compilationId &&
      status &&
      ["completed", "failed"].includes(status) &&
      completedCompilation.current !== compilationId
    ) {
      completedCompilation.current = compilationId;
      void refreshWorkspace(projectId);
    }
  }, [compilationId, projectId, status]);

  return (
    <section
      className={[
        "flex min-h-0 flex-col overflow-hidden",
        mode === "full" ? "h-full rounded-xl border border-edge bg-ink-900" : "border-t border-edge",
      ].join(" ")}
    >
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-edge px-3">
        <div className="flex items-center gap-2">
          <FileDown className="h-4 w-4 text-indigo-300" aria-hidden="true" />
          <h2 className="text-xs font-semibold uppercase tracking-wide text-mist">PDF preview</h2>
        </div>
        <div className="flex items-center gap-2">
          {status === "completed" ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />
          ) : null}
          {status === "failed" ? (
            <span className="text-[11px] font-medium text-red-400">failed</span>
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
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {inFlight ? "Compiling..." : "Compile"}
          </button>
        </div>
      </div>
      <div className={["min-h-0 flex-1 bg-ink-950", mode === "compact" ? "h-64" : ""].join(" ")}>
        {compilation?.has_pdf ? (
          <iframe
            className="h-full w-full border-0 bg-white"
            title="Compiled PDF"
            src={getPdfUrl(compilation.id)}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <FileDown className="h-6 w-6 text-fog" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium text-mist">
              {compilation?.status ? `Compilation ${compilation.status}` : "No PDF compiled yet"}
            </p>
            <p className="mt-1 max-w-md text-xs leading-5 text-fog">
              {compilation?.error ?? "Hit Compile to build the project with Tectonic."}
            </p>
            {compilation?.logs && compilation.status === "failed" ? (
              <pre className="mt-3 max-h-48 w-full max-w-2xl overflow-auto rounded-lg border border-edge bg-ink-900 p-3 text-left font-mono text-[10px] leading-4 text-fog">
                {compilation.logs}
              </pre>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
