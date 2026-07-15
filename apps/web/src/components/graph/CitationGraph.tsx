import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, GitBranch, Layers, Loader2, Network, Sparkles } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";

import { expandGraph, getJob, getNeighborhood, getProjectGraph } from "@/lib/api";
import { refreshWorkspace } from "@/lib/refresh";
import type { CitationNeighborhood } from "@/lib/schemas";

import { PaperDetailPanel } from "./PaperDetailPanel";

type PaperRole = "seed" | "reference" | "citer" | "both" | "project" | "foundation";

type PaperNodeData = {
  title: string;
  year: number | null;
  citedBy: number;
  role: PaperRole;
  connectionCount: number;
  [key: string]: unknown;
};

type PaperNode = Node<PaperNodeData, "paper">;

const ROLE_STYLE: Record<PaperRole, { border: string; badge: string; dot: string }> = {
  seed: { border: "border-indigo-400/80", badge: "text-indigo-200", dot: "#3157d5" },
  reference: { border: "border-cyan-400/50", badge: "text-cyan-200", dot: "#227b76" },
  citer: { border: "border-emerald-400/50", badge: "text-emerald-300", dot: "#227b5a" },
  both: { border: "border-violet-400/50", badge: "text-violet-300", dot: "#5b55a7" },
  project: { border: "border-indigo-400/45", badge: "text-indigo-200", dot: "#3157d5" },
  foundation: { border: "border-amber-400/50", badge: "text-amber-300", dot: "#d96c3b" },
};

function PaperGraphNode({ data, selected }: NodeProps<PaperNode>) {
  const style = ROLE_STYLE[data.role];
  return (
    <div
      className={[
        "w-[200px] rounded-lg border bg-ink-800/95 px-3 py-2 shadow-lg shadow-black/30 transition",
        style.border,
        data.role === "seed" ? "bg-indigo-500/15" : "",
        selected ? "ring-2 ring-indigo-400/70" : "",
      ].join(" ")}
    >
      <Handle type="target" position={Position.Left} className="!h-1 !w-1 !border-0 !bg-transparent" />
      <Handle type="source" position={Position.Right} className="!h-1 !w-1 !border-0 !bg-transparent" />
      <p className="line-clamp-2 text-[11px] font-medium leading-4 text-snow">{data.title}</p>
      <p className={["mt-1 font-mono text-[10px]", style.badge].join(" ")}>
        {data.role === "foundation" && data.connectionCount > 1
          ? `shared by ${data.connectionCount} project papers`
          : `${data.year ?? "n.d."} · ${data.citedBy.toLocaleString()} cites`}
      </p>
    </div>
  );
}

const NODE_TYPES = { paper: PaperGraphNode };

function layoutGraph(
  graph: CitationNeighborhood | undefined,
): { nodes: PaperNode[]; edges: Edge[]; seedId: string | null } {
  const visible = graph
    ? graph.nodes.filter((node) => !node.is_stub && Boolean(node.title?.trim()))
    : [];
  if (visible.length === 0) {
    return { nodes: [], edges: [], seedId: null };
  }

  const visibleIds = new Set(visible.map((node) => node.id));
  const seed = visible.find((node) => node.is_seed) ?? visible[0];
  const edges = (graph?.edges ?? []).filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
  );

  // classify hop-1 nodes: seed cites references, citers cite the seed
  const roles = new Map<string, PaperRole>();
  for (const edge of edges) {
    if (edge.source === seed.id) {
      roles.set(edge.target, roles.get(edge.target) === "citer" ? "both" : "reference");
    }
    if (edge.target === seed.id) {
      roles.set(edge.source, roles.get(edge.source) === "reference" ? "both" : "citer");
    }
  }

  function makeNode(node: (typeof visible)[number], role: PaperRole, x: number, y: number): PaperNode {
    return {
      id: node.id,
      type: "paper",
      position: { x, y },
      data: {
        title: node.title ?? "Untitled",
        year: node.year ?? null,
        citedBy: node.cited_by_count,
        role,
        connectionCount: node.connection_count,
      },
    };
  }

  // citers flow in from the left, references exit to the right
  const left = visible.filter((n) => n.id !== seed.id && roles.get(n.id) === "citer");
  const right = visible.filter(
    (n) => n.id !== seed.id && (roles.get(n.id) === "reference" || roles.get(n.id) === "both"),
  );
  const orphan = visible.filter((n) => n.id !== seed.id && !roles.get(n.id));
  const byCites = (a: (typeof visible)[number], b: (typeof visible)[number]) =>
    b.cited_by_count - a.cited_by_count;
  left.sort(byCites);
  right.sort(byCites);

  const column = (nodes: typeof visible, x: number, role?: PaperRole): PaperNode[] =>
    nodes.map((node, index) =>
      makeNode(node, role ?? roles.get(node.id) ?? "reference", x, (index - (nodes.length - 1) / 2) * 92),
    );

  const flowNodes: PaperNode[] = [
    makeNode(seed, "seed", 0, 0),
    ...column(left, -420, "citer"),
    ...column(right, 420),
    // unconnected papers park below the seed
    ...orphan.map((node, index) =>
      makeNode(node, "reference", (index - (orphan.length - 1) / 2) * 220, 260),
    ),
  ];

  const flowEdges: Edge[] = edges.map((edge, index) => {
    const touchesSeed = edge.source === seed.id || edge.target === seed.id;
    const color =
      edge.source === seed.id ? "#227b76" : edge.target === seed.id ? "#227b5a" : "#9aa198";
    return {
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: touchesSeed,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
      style: { stroke: color, strokeWidth: touchesSeed ? 1.6 : 1, opacity: touchesSeed ? 0.9 : 0.45 },
    };
  });

  return { nodes: flowNodes, edges: flowEdges, seedId: seed.id };
}

// overview: every project paper laid out as a timeline — columns by year,
// citation edges among them. Gives the "whole bibliography at a glance" view.
function layoutOverview(
  graph: CitationNeighborhood | undefined,
): { nodes: PaperNode[]; edges: Edge[]; seedId: string | null } {
  const visible = graph
    ? graph.nodes.filter((node) => !node.is_stub && Boolean(node.title?.trim()))
    : [];
  if (visible.length === 0) {
    return { nodes: [], edges: [], seedId: null };
  }

  const byYear = new Map<number, typeof visible>();
  for (const node of visible) {
    const year = node.year ?? 0; // unknown years group in a leading column
    const bucket = byYear.get(year) ?? [];
    bucket.push(node);
    byYear.set(year, bucket);
  }
  const years = [...byYear.keys()].sort((a, b) => a - b);

  const flowNodes: PaperNode[] = [];
  years.forEach((year, columnIndex) => {
    const column = byYear.get(year) ?? [];
    column.sort((a, b) => b.cited_by_count - a.cited_by_count);
    column.forEach((node, rowIndex) => {
      flowNodes.push({
        id: node.id,
        type: "paper",
        position: {
          x: columnIndex * 280,
          y: (rowIndex - (column.length - 1) / 2) * 112,
        },
        data: {
          title: node.title ?? "Untitled",
          year: node.year ?? null,
          citedBy: node.cited_by_count,
          role: node.role === "foundation" ? "foundation" : "project",
          connectionCount: node.connection_count,
        },
      });
    });
  });

  const visibleIds = new Set(visible.map((node) => node.id));
  const flowEdges: Edge[] = (graph?.edges ?? [])
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .map((edge, index) => ({
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#7d8792" },
      style: { stroke: "#7d8792", strokeWidth: 1.2, opacity: 0.65 },
    }));

  return { nodes: flowNodes, edges: flowEdges, seedId: null };
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] text-fog">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

export function CitationGraph({
  projectId,
  paperId,
  onSelectPaper,
  mode = "compact",
}: {
  projectId: string;
  paperId: string | null;
  onSelectPaper: (paperId: string | null) => void;
  mode?: "compact" | "full";
}) {
  const [topN, setTopN] = useState(10);
  const [expandJobId, setExpandJobId] = useState<string | null>(null);
  // clicking a node opens its detail panel; the graph only re-centers when the
  // user asks for it from the panel or picks a different bibliography entry
  const [inspectedPaperId, setInspectedPaperId] = useState<string | null>(null);
  const completedExpandJob = useRef<string | null>(null);

  const neighborhoodQuery = useQuery({
    queryKey: ["citation-neighborhood", paperId],
    queryFn: () => getNeighborhood(paperId ?? "", 12),
    enabled: Boolean(paperId),
    staleTime: 60_000,
  });
  // no seed selected -> whole-project overview
  const overviewQuery = useQuery({
    queryKey: ["project-graph", projectId],
    queryFn: () => getProjectGraph(projectId),
    enabled: !paperId,
    staleTime: 60_000,
  });
  const expandMutation = useMutation({
    mutationFn: () => expandGraph(projectId, topN),
    onSuccess: (result) => {
      setExpandJobId(result.job_id);
    },
  });
  const expandJobQuery = useQuery({
    queryKey: ["job", expandJobId],
    queryFn: () => getJob(expandJobId ?? ""),
    enabled: Boolean(expandJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    },
  });

  const expandStatus = expandJobQuery.data?.status;

  useEffect(() => {
    if (
      expandJobId &&
      expandStatus &&
      ["completed", "failed"].includes(expandStatus) &&
      completedExpandJob.current !== expandJobId
    ) {
      completedExpandJob.current = expandJobId;
      void refreshWorkspace(projectId);
    }
  }, [expandJobId, expandStatus, projectId]);

  const graph = useMemo(
    () =>
      paperId ? layoutGraph(neighborhoodQuery.data) : layoutOverview(overviewQuery.data),
    [paperId, neighborhoodQuery.data, overviewQuery.data],
  );
  const isFetching = paperId ? neighborhoodQuery.isFetching : overviewQuery.isFetching;
  const isLoading = paperId ? neighborhoodQuery.isLoading : overviewQuery.isLoading;
  const graphData = paperId ? neighborhoodQuery.data : overviewQuery.data;
  const heightClass = mode === "full" ? "h-full min-h-[480px]" : "h-72";

  return (
    <section
      className={[
        "flex min-h-0 flex-col overflow-hidden",
        mode === "full" ? "h-full rounded-xl border border-edge bg-ink-900" : "border-t border-edge",
      ].join(" ")}
    >
      <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-edge px-3">
        <div className="flex min-w-0 items-center gap-2">
          <Network className="h-4 w-4 shrink-0 text-indigo-300" aria-hidden="true" />
          <h2 className="truncate text-xs font-semibold uppercase tracking-wide text-mist">
            {paperId ? "Citation neighborhood" : "All project papers"}
          </h2>
          {isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-fog" aria-hidden="true" />
          ) : null}
        </div>
        <div className="hidden items-center gap-3 lg:flex">
          {paperId ? (
            <>
              <LegendDot color="#3157d5" label="seed" />
              <LegendDot color="#227b76" label="seed cites" />
              <LegendDot color="#227b5a" label="cites seed" />
            </>
          ) : (
            <>
              <LegendDot color="#3157d5" label="project paper" />
              <LegendDot color="#d96c3b" label="shared foundation" />
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {paperId ? (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md border border-edge-2 bg-ink-800 px-2 py-1 text-xs font-medium text-mist hover:border-indigo-400/50 hover:text-indigo-200"
              onClick={() => onSelectPaper(null)}
              title="Show every paper in the project"
            >
              <Layers className="h-3.5 w-3.5" aria-hidden="true" />
              All papers
            </button>
          ) : null}
          {expandStatus === "completed" ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />
          ) : null}
          <select
            className="rounded-md border border-edge-2 bg-ink-800 px-2 py-1 text-xs text-mist outline-none focus:border-indigo-400/60"
            value={topN}
            onChange={(event) => setTopN(Number(event.target.value))}
            aria-label="Expand graph count"
          >
            {[5, 10, 15, 25].map((value) => (
              <option key={value} value={value}>
                top {value}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-edge-2 bg-ink-800 px-2 py-1 text-xs font-medium text-mist hover:border-indigo-400/50 hover:text-indigo-200 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => expandMutation.mutate()}
            disabled={expandMutation.isPending || Boolean(expandStatus === "running")}
            title="Fetch more citation edges from OpenAlex"
          >
            {expandMutation.isPending || expandStatus === "running" || expandStatus === "queued" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Enrich
          </button>
        </div>
      </div>

      <div className={`relative min-h-0 flex-1 ${heightClass} bg-ink-950`}>
        {graphData?.stats.hidden_stubs ? (
          <div className="pointer-events-none absolute left-3 top-3 z-10 max-w-xs rounded-md border border-amber-400/20 bg-ink-900/90 px-2.5 py-1.5 text-[10px] leading-4 text-amber-100 shadow-lg backdrop-blur">
            {graphData.stats.hidden_stubs} indexed reference
            {graphData.stats.hidden_stubs === 1 ? " is" : "s are"} awaiting metadata. Enrich to
            turn the strongest ones into readable nodes.
          </div>
        ) : null}
        {graph.nodes.length > 0 ? (
          <ReactFlow
            key={graph.seedId ?? paperId ?? "overview"}
            colorMode="light"
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={NODE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.25}
            maxZoom={1.75}
            proOptions={{ hideAttribution: true }}
            nodesConnectable={false}
            nodesDraggable
            onNodeClick={(_, node) => setInspectedPaperId(node.id)}
          >
            <Background color="#dfe1da" gap={20} variant={BackgroundVariant.Dots} />
            <Controls showInteractive={false} position="bottom-left" />
            {mode === "full" ? (
              <MiniMap
                pannable
                zoomable
                className="!bg-ink-850"
                maskColor="rgba(247, 247, 243, 0.76)"
                nodeColor={(node) =>
                  ROLE_STYLE[((node.data as PaperNodeData | undefined)?.role ?? "reference") as PaperRole]
                    .dot
                }
              />
            ) : null}
          </ReactFlow>
        ) : isLoading ? (
          <div className="grid h-full place-items-center">
            <Loader2 className="h-5 w-5 animate-spin text-fog" aria-hidden="true" />
          </div>
        ) : (
          <div className="grid h-full place-items-center px-6 text-center">
            <div>
              <GitBranch className="mx-auto h-7 w-7 text-fog" aria-hidden="true" />
              <p className="mt-3 text-sm font-medium text-mist">
                {paperId ? "No graph neighborhood yet" : "No papers imported yet"}
              </p>
              <p className="mt-1 text-xs leading-5 text-fog">
                {paperId
                  ? "Hit Enrich to pull citation edges from OpenAlex, or import more papers."
                  : "Import papers to see the whole project graph; click a bibliography entry to focus on one paper."}
              </p>
            </div>
          </div>
        )}

        {inspectedPaperId ? (
          <PaperDetailPanel
            paperId={inspectedPaperId}
            projectId={projectId}
            isSeed={inspectedPaperId === graph.seedId}
            onClose={() => setInspectedPaperId(null)}
            onFocus={(id) => onSelectPaper(id)}
          />
        ) : null}
      </div>
    </section>
  );
}
