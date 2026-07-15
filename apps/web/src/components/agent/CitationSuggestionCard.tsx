import { Quote, SendToBack } from "lucide-react";

import type { Recommendation } from "@/lib/schemas";

export function CitationSuggestionCard({
  recommendation,
  onInsertCitation,
}: {
  recommendation: Recommendation;
  onInsertCitation: (bibtexKey: string) => void;
}) {
  return (
    <article className="fade-up rounded-lg border border-edge bg-ink-800/70 p-3">
      <div className="flex items-start gap-2">
        <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-300" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h4 className="line-clamp-2 text-[13px] font-semibold leading-5 text-snow">
            {recommendation.title ?? recommendation.paper_id}
          </h4>
          <p className="mt-1 font-mono text-[11px] text-fog">
            score {recommendation.score.toFixed(3)} ·{" "}
            {recommendation.bibtex_key ?? (recommendation.is_stub ? "stub" : "no key")}
          </p>
        </div>
        <button
          type="button"
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-edge-2 bg-ink-750 px-2 py-1 text-[11px] font-medium text-mist hover:border-indigo-400/50 hover:text-indigo-200 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!recommendation.bibtex_key}
          onClick={() => {
            if (recommendation.bibtex_key) {
              onInsertCitation(recommendation.bibtex_key);
            }
          }}
        >
          <SendToBack className="h-3 w-3" aria-hidden="true" />
          Cite
        </button>
      </div>
      <p className="mt-2 text-xs leading-5 text-mist">{recommendation.reason}</p>
      {recommendation.evidence_snippets[0] ? (
        <blockquote className="mt-2 border-l-2 border-indigo-400/40 pl-2.5 text-[11px] leading-5 text-fog">
          {recommendation.evidence_snippets[0]}
        </blockquote>
      ) : null}
    </article>
  );
}
