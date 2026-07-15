import { Check, FileDiff, Loader2 } from "lucide-react";
import { useMutation } from "@tanstack/react-query";

import { acceptPatch } from "@/lib/api";
import { refreshWorkspace } from "@/lib/refresh";
import type { TimelineItem } from "@/stores/agentStore";

type PatchItem = Extract<TimelineItem, { kind: "patch" }>;

function pretty(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

export function PatchReviewCard({
  projectId,
  patch,
  onAccepted,
}: {
  projectId: string;
  patch: PatchItem;
  onAccepted: (toolCallId: string) => void;
}) {
  const acceptMutation = useMutation({
    mutationFn: () => acceptPatch(patch.toolCallId),
    onSuccess: async () => {
      onAccepted(patch.toolCallId);
      await refreshWorkspace(projectId);
    },
  });
  const accepted = patch.status === "accepted";

  return (
    <article className="fade-up overflow-hidden rounded-lg border border-amber-400/25 bg-amber-400/5">
      <div className="flex items-center justify-between gap-2 border-b border-amber-400/15 px-3 py-2">
        <div className="flex items-center gap-2">
          <FileDiff className="h-3.5 w-3.5 text-amber-300" aria-hidden="true" />
          <h4 className="text-xs font-semibold text-amber-200">
            {accepted ? "Patch applied" : "Proposed edit"}
          </h4>
        </div>
        {accepted ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400">
            <Check className="h-3 w-3" aria-hidden="true" />
            Applied
          </span>
        ) : (
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md bg-amber-400/90 px-2.5 py-1 text-[11px] font-semibold text-ink-950 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={acceptMutation.isPending}
            onClick={() => acceptMutation.mutate()}
          >
            {acceptMutation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            ) : (
              <Check className="h-3 w-3" aria-hidden="true" />
            )}
            Apply
          </button>
        )}
      </div>
      <pre className="max-h-44 overflow-auto p-3 font-mono text-[11px] leading-5 text-mist">
        {pretty(patch.preview)}
      </pre>
      {acceptMutation.error ? (
        <p className="border-t border-amber-400/15 px-3 py-2 text-xs text-red-300">
          {acceptMutation.error.message}
        </p>
      ) : null}
    </article>
  );
}
