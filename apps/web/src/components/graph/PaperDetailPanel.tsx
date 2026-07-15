import { useEffect, useState } from "react";
import {
  BookMarked,
  Check,
  Copy,
  Crosshair,
  ExternalLink,
  Loader2,
  X,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { getPaperDetail } from "@/lib/api";

export function PaperDetailPanel({
  paperId,
  projectId,
  isSeed,
  onClose,
  onFocus,
}: {
  paperId: string;
  projectId: string;
  isSeed: boolean;
  onClose: () => void;
  onFocus: (paperId: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const detailQuery = useQuery({
    queryKey: ["paper-detail", paperId, projectId],
    queryFn: () => getPaperDetail(paperId, projectId),
  });

  useEffect(() => {
    setCopied(false);
  }, [paperId]);

  const paper = detailQuery.data;

  async function copyBibtex() {
    if (!paper?.bibtex) {
      return;
    }
    await navigator.clipboard.writeText(paper.bibtex);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <aside className="fade-up absolute inset-y-3 right-3 z-20 flex w-[340px] max-w-[calc(100%-24px)] flex-col overflow-hidden rounded-xl border border-edge-2 bg-ink-850/95 shadow-2xl shadow-black/50 backdrop-blur">
      <div className="flex items-start justify-between gap-2 border-b border-edge px-4 py-3">
        <div className="flex items-center gap-2">
          <BookMarked className="h-4 w-4 shrink-0 text-indigo-300" aria-hidden="true" />
          <span className="text-[11px] font-semibold uppercase tracking-wide text-fog">
            Paper details
          </span>
        </div>
        <button
          type="button"
          className="grid h-6 w-6 place-items-center rounded text-fog hover:bg-ink-750 hover:text-mist"
          onClick={onClose}
          aria-label="Close paper details"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {detailQuery.isLoading ? (
        <div className="grid flex-1 place-items-center">
          <Loader2 className="h-5 w-5 animate-spin text-fog" aria-hidden="true" />
        </div>
      ) : detailQuery.error || !paper ? (
        <p className="p-4 text-xs text-red-300">Could not load this paper.</p>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <h3 className="text-sm font-semibold leading-6 text-snow">
            {paper.title ?? "Untitled paper"}
          </h3>
          <p className="mt-1.5 text-xs leading-5 text-fog">
            {[
              paper.year ? String(paper.year) : null,
              paper.venue,
              `${paper.cited_by_count.toLocaleString()} citations`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {paper.authors.length > 0 ? (
            <p className="mt-2 text-xs leading-5 text-mist">
              {paper.authors.slice(0, 8).join(", ")}
              {paper.authors.length > 8 ? ` +${paper.authors.length - 8} more` : ""}
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {paper.bibtex_key ? (
              <span className="rounded border border-indigo-400/30 bg-indigo-500/10 px-1.5 py-0.5 font-mono text-[10px] text-indigo-200">
                {paper.bibtex_key}
              </span>
            ) : null}
            {paper.is_stub ? (
              <span className="rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                stub — not fully imported
              </span>
            ) : null}
            {paper.concepts.slice(0, 4).map((concept) => (
              <span
                key={concept}
                className="rounded border border-edge bg-ink-800 px-1.5 py-0.5 text-[10px] text-fog"
              >
                {concept}
              </span>
            ))}
          </div>

          {paper.abstract ? (
            <div className="mt-3">
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-fog">
                Abstract
              </h4>
              <p className="mt-1.5 text-xs leading-[1.7] text-mist">{paper.abstract}</p>
            </div>
          ) : (
            <p className="mt-3 text-xs italic text-fog">No abstract available.</p>
          )}

          {paper.bibtex ? (
            <div className="mt-3">
              <div className="flex items-center justify-between">
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-fog">
                  BibTeX
                </h4>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded border border-edge-2 bg-ink-800 px-1.5 py-0.5 text-[10px] font-medium text-mist hover:border-indigo-400/50 hover:text-indigo-200"
                  onClick={() => void copyBibtex()}
                >
                  {copied ? (
                    <Check className="h-3 w-3 text-emerald-400" aria-hidden="true" />
                  ) : (
                    <Copy className="h-3 w-3" aria-hidden="true" />
                  )}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <pre className="mt-1.5 max-h-36 overflow-auto rounded-md border border-edge bg-ink-950/70 p-2 font-mono text-[10px] leading-4 text-fog">
                {paper.bibtex}
              </pre>
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2 pb-1">
            {paper.doi ? (
              <a
                className="inline-flex items-center gap-1 rounded-md border border-edge-2 bg-ink-800 px-2 py-1 text-[11px] text-mist hover:border-indigo-400/50 hover:text-indigo-200"
                href={`https://doi.org/${paper.doi}`}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
                DOI
              </a>
            ) : null}
            {paper.url ? (
              <a
                className="inline-flex items-center gap-1 rounded-md border border-edge-2 bg-ink-800 px-2 py-1 text-[11px] text-mist hover:border-indigo-400/50 hover:text-indigo-200"
                href={paper.url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
                Landing page
              </a>
            ) : null}
            {paper.pdf_url ? (
              <a
                className="inline-flex items-center gap-1 rounded-md border border-edge-2 bg-ink-800 px-2 py-1 text-[11px] text-mist hover:border-indigo-400/50 hover:text-indigo-200"
                href={paper.pdf_url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
                PDF
              </a>
            ) : null}
          </div>
        </div>
      )}

      {!isSeed && paper ? (
        <div className="border-t border-edge p-3">
          <button
            type="button"
            className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-accent-deep px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
            onClick={() => onFocus(paperId)}
          >
            <Crosshair className="h-3.5 w-3.5" aria-hidden="true" />
            Center graph on this paper
          </button>
        </div>
      ) : null}
    </aside>
  );
}
