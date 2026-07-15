import { useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronRight,
  FileCode2,
  FileSearch,
  GitBranch,
  Hammer,
  Import,
  Loader2,
  Play,
  Quote,
  ScrollText,
  Search,
  Square,
} from "lucide-react";

import type { TimelineItem } from "@/stores/agentStore";

type ToolItem = Extract<TimelineItem, { kind: "tool" }>;

const TOOL_META: Record<string, { active: string; done: string; icon: typeof Hammer }> = {
  search_papers: { active: "Searching papers", done: "Searched papers", icon: Search },
  import_paper: { active: "Importing paper", done: "Imported paper", icon: Import },
  get_paper: { active: "Reading paper", done: "Read paper", icon: ScrollText },
  get_citation_neighborhood: {
    active: "Exploring citation graph",
    done: "Explored citation graph",
    icon: GitBranch,
  },
  retrieve_evidence: { active: "Retrieving evidence", done: "Retrieved evidence", icon: FileSearch },
  rank_related_work: { active: "Ranking related work", done: "Ranked related work", icon: Quote },
  suggest_bibtex: { active: "Preparing BibTeX", done: "Prepared BibTeX", icon: FileCode2 },
  inspect_latex_project: {
    active: "Inspecting project files",
    done: "Inspected project files",
    icon: FileSearch,
  },
  patch_latex_file: { active: "Proposing an edit", done: "Proposed an edit", icon: FileCode2 },
  compile_latex: { active: "Compiling LaTeX", done: "Compiled LaTeX", icon: Play },
};

function prettyArgs(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export function ToolCallChip({ item }: { item: ToolItem }) {
  const [expanded, setExpanded] = useState(false);
  const meta = TOOL_META[item.tool] ?? { active: item.tool, done: item.tool, icon: Hammer };
  const Icon = meta.icon;
  const running = item.status === "running";

  return (
    <div className="fade-up overflow-hidden rounded-lg border border-edge bg-ink-800/70">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-ink-750"
        onClick={() => setExpanded((open) => !open)}
      >
        <ChevronRight
          className={[
            "h-3 w-3 shrink-0 text-fog transition-transform",
            expanded ? "rotate-90" : "",
          ].join(" ")}
          aria-hidden="true"
        />
        <Icon
          className={[
            "h-3.5 w-3.5 shrink-0",
            item.status === "error" ? "text-red-400" : "text-indigo-300",
          ].join(" ")}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-mist">
          {running ? meta.active : item.status === "stopped" ? `${meta.active} — stopped` : meta.done}
          <span className="ml-2 font-mono text-[11px] text-fog">{item.tool}</span>
        </span>
        {running ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo-300" aria-hidden="true" />
        ) : item.status === "error" ? (
          <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-400" aria-hidden="true" />
        ) : item.status === "stopped" ? (
          <Square className="h-3 w-3 shrink-0 fill-current text-fog" aria-hidden="true" />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-hidden="true" />
        )}
      </button>
      {expanded ? (
        <div className="space-y-2 border-t border-edge px-3 py-2">
          {item.args && item.args !== "{}" ? (
            <pre className="max-h-40 overflow-auto rounded-md bg-ink-950/70 p-2 font-mono text-[11px] leading-4 text-fog">
              {prettyArgs(item.args)}
            </pre>
          ) : null}
          {item.summary ? (
            <p
              className={[
                "text-xs leading-5",
                item.status === "error" ? "text-red-300" : "text-mist",
              ].join(" ")}
            >
              {item.summary}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
