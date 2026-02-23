"use client";

import type { NVL } from "@neo4j-nvl/base";
import { InteractiveNvlWrapper } from "@neo4j-nvl/react";
import JsonView from "@uiw/react-json-view";
import {
  DatabaseZap,
  Loader2,
  Maximize2,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { env } from "@/env";

// Turbopack can't resolve `new URL('./worker.js', import.meta.url)` for SharedWorkers
// inside node_modules. Intercept SharedWorker construction by name and redirect to
// the pre-bundled files served from /public/workers/nvl/.
if (typeof window !== "undefined" && window.SharedWorker) {
  const Original = window.SharedWorker;
  class NvlSharedWorker extends Original {
    constructor(url: string | URL, options?: string | WorkerOptions) {
      const opts = typeof options === "string" ? { name: options } : options;
      if (opts?.name === "CoseBilkentLayout") {
        super(
          "/workers/nvl/cosebilkent-layout/CoseBilkentLayout.worker.js",
          opts,
        );
      } else if (opts?.name === "HierarchicalLayout") {
        super(
          "/workers/nvl/hierarchical-layout/HierarchicalLayout.worker.js",
          opts,
        );
      } else {
        super(url, options);
      }
    }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  window.SharedWorker = NvlSharedWorker as any;
}

/** Node shape for NVL: at least id; extra fields are metadata. */
export type GraphNode = { id: string; [key: string]: unknown };
/** Relationship shape for NVL: id, from, to; extra fields are metadata. */
export type GraphEdge = {
  id: string;
  from: string;
  to: string;
  [key: string]: unknown;
};

const NODE_TYPE_COLORS: Record<string, string> = {
  agent: "#bfbb1d",
  llm: "#bfbb1d",
  boundary: "#00b4ff",
  session: "#84c296",
  thread: "#c9c893",
  tool: "#e3d0ff",
  trace: "#ee729f",
};

function nodeColor(node: GraphNode): string | undefined {
  const riskScore = node.node_risk_score as number | undefined;
  if (riskScore != null && riskScore > 0) {
    if (riskScore >= 0.7) return "#ef4444";
    if (riskScore >= 0.4) return "#f59e0b";
    return "#eab308";
  }
  const labelKey = (node.label ?? "").toString().toLowerCase();
  const typeKey = (node.type ?? "").toString().toLowerCase();
  return NODE_TYPE_COLORS[labelKey] ?? NODE_TYPE_COLORS[typeKey];
}

type SelectedItem =
  | { type: "node"; data: Record<string, unknown> }
  | { type: "edge"; data: Record<string, unknown> }
  | null;

const LEGEND_ITEMS: { color: string; label: string }[] = [
  { color: "#ef4444", label: "High risk (>= 0.7)" },
  { color: "#f59e0b", label: "Medium risk (>= 0.4)" },
  { color: "#eab308", label: "Low risk (> 0)" },
  { color: NODE_TYPE_COLORS.agent!, label: "Agent / LLM" },
  { color: NODE_TYPE_COLORS.tool!, label: "Tool" },
  { color: NODE_TYPE_COLORS.trace!, label: "Trace" },
  { color: NODE_TYPE_COLORS.session!, label: "Session" },
  { color: NODE_TYPE_COLORS.thread!, label: "Thread" },
];

function GraphLegend() {
  return (
    <div className="absolute top-3 left-3 z-10 flex flex-col gap-1.5 rounded-lg border bg-background/90 backdrop-blur-sm px-3 py-2.5 text-xs">
      {LEGEND_ITEMS.map(({ color, label }) => (
        <div key={label} className="flex items-center gap-2">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
            style={{ backgroundColor: color }}
          />
          <span className="text-muted-foreground">{label}</span>
        </div>
      ))}
    </div>
  );
}

function MetadataPanel({ selected }: { selected: SelectedItem }) {
  if (!selected) return null;
  return (
    <div
      className="absolute bottom-4 right-4 z-10 max-h-[20vh] w-100 overflow-auto rounded-xl border bg-background p-3 text-sm"
      style={{ bottom: 16, right: 16 }}
    >
      <JsonView
        value={selected.data}
        collapsed={2}
        style={{ fontSize: "12px" }}
      />
    </div>
  );
}

const API_URL = env.NEXT_PUBLIC_LANGSMITH_API_URL;

function SentinelReportView({ threadId }: { threadId: string | null }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [report, setReport] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!threadId || !API_URL) {
      setLoading(false);
      return;
    }
    setLoading(true);
    fetch(`${API_URL}/threads/${threadId}/sentinel`)
      .then((res) => {
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then((data) => setReport(data))
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [threadId]);

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (!report) {
    return (
      <div className="flex h-full w-full items-center justify-center text-muted-foreground">
        <p className="text-center text-base">No report available. Run the thread to generate one.</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      <JsonView
        value={report}
        collapsed={2}
        style={{ fontSize: "12px" }}
      />
    </div>
  );
}

function ToolbarButton({
  tooltip,
  onClick,
  disabled,
  children,
}: {
  tooltip: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors disabled:opacity-40 disabled:pointer-events-none"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{tooltip}</TooltipContent>
    </Tooltip>
  );
}

type ViewMode = "graph" | "report";

function GraphToolbar({
  threadId,
  view,
  onViewChange,
  onIngestComplete,
  zoomIn,
  zoomOut,
  fitAll,
  hasGraph,
}: {
  threadId?: string;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
  onIngestComplete?: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  fitAll: () => void;
  hasGraph: boolean;
}) {
  const [ingesting, setIngesting] = useState(false);
  const [clearing, setClearing] = useState(false);

  const handleIngest = useCallback(async () => {
    if (!threadId || !API_URL) return;
    setIngesting(true);
    try {
      const res = await fetch(`${API_URL}/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: [threadId] }),
      });
      if (!res.ok) throw new Error(`Ingest failed: ${res.status}`);
      onIngestComplete?.();
    } catch (err) {
      console.error("Ingest error:", err);
    } finally {
      setIngesting(false);
    }
  }, [threadId, onIngestComplete]);

  const handleClear = useCallback(async () => {
    if (!API_URL || !threadId) return;
    setClearing(true);
    try {
      const res = await fetch(`${API_URL}/ingest/${threadId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Clear failed: ${res.status}`);
      onIngestComplete?.();
    } catch (err) {
      console.error("Clear error:", err);
    } finally {
      setClearing(false);
    }
  }, [threadId, onIngestComplete]);

  return (
    <TooltipProvider>
      <div className="flex h-10 shrink-0 items-center justify-between border-b bg-background/80 backdrop-blur-sm px-2">
        <div className="flex items-center gap-0.5">
          <ToolbarButton
            tooltip="Ingest thread"
            onClick={handleIngest}
            disabled={ingesting || !threadId}
          >
            {ingesting ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <DatabaseZap className="h-5 w-5" />
            )}
          </ToolbarButton>

          <div className="mx-1 h-4 w-px bg-border" />

          <ToolbarButton
            tooltip="Clear this thread"
            onClick={handleClear}
            disabled={clearing || !threadId}
          >
            {clearing ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Trash2 className="h-5 w-5" />
            )}
          </ToolbarButton>
        </div>

        <div className="flex rounded-md border border-border bg-muted/30 p-0.5">
          <button
            type="button"
            onClick={() => onViewChange("graph")}
            className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
              view === "graph"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Graph
          </button>
          <button
            type="button"
            onClick={() => onViewChange("report")}
            className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
              view === "report"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Report
          </button>
        </div>

        <div className="flex items-center gap-0.5">
          <ToolbarButton
            tooltip="Zoom in"
            onClick={zoomIn}
            disabled={!hasGraph || view === "report"}
          >
            <ZoomIn className="h-5 w-5" />
          </ToolbarButton>
          <ToolbarButton
            tooltip="Zoom out"
            onClick={zoomOut}
            disabled={!hasGraph || view === "report"}
          >
            <ZoomOut className="h-5 w-5" />
          </ToolbarButton>
          <ToolbarButton
            tooltip="Fit to screen"
            onClick={fitAll}
            disabled={!hasGraph || view === "report"}
          >
            <Maximize2 className="h-5 w-5" />
          </ToolbarButton>
        </div>
      </div>
    </TooltipProvider>
  );
}

type NvlGraphProps = {
  nodes?: GraphNode[];
  rels?: GraphEdge[];
  threadId?: string;
  onGraphUpdate?: () => void;
};

export function NvlGraph({
  nodes = [],
  rels = [],
  threadId,
  onGraphUpdate,
}: NvlGraphProps) {
  const [selected, setSelected] = useState<SelectedItem>(null);
  const [view, setView] = useState<ViewMode>("graph");
  const nvlRef = useRef<NVL>(null);

  const nodeById = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const edgeById = Object.fromEntries(rels.map((e) => [e.id, e]));

  const onNodeClick = useCallback(
    (node: unknown) => {
      const id = (node as { id?: string })?.id ?? "";
      const original = nodeById[id] ?? { id };
      setSelected({ type: "node", data: original as Record<string, unknown> });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [nodes],
  );
  const onRelationshipClick = useCallback(
    (rel: unknown) => {
      const id = (rel as { id?: string })?.id ?? "";
      const original = edgeById[id] ?? { id };
      setSelected({ type: "edge", data: original as Record<string, unknown> });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [rels],
  );
  const onCanvasClick = useCallback(() => {
    setSelected(null);
  }, []);

  const hasGraph = nodes.length > 0 || rels.length > 0;
  const nvlNodes = hasGraph
    ? nodes.map((n) => ({
        ...n,
        color: nodeColor(n),
        caption:
          (n.name as string | undefined) ??
          (n.thread_id as string | undefined) ??
          (n.trace_id as string | undefined) ??
          (n.session_id as string | undefined) ??
          n.id,
      }))
    : [];
  const nvlRels = hasGraph
    ? rels.map((e) => ({ ...e, caption: e.type as string | undefined }))
    : [];

  const zoomIn = useCallback(() => {
    const nvl = nvlRef.current;
    if (nvl) nvl.setZoom((nvl.getScale() ?? 1) * 1.3);
  }, []);

  const zoomOut = useCallback(() => {
    const nvl = nvlRef.current;
    if (nvl) nvl.setZoom((nvl.getScale() ?? 1) / 1.3);
  }, []);

  const fitAll = useCallback(() => {
    nvlRef.current?.fit(nvlNodes.map((n) => n.id));
  }, [nvlNodes]);

  return (
    <div className="flex h-full w-full flex-col">
      <GraphToolbar
        threadId={threadId}
        view={view}
        onViewChange={setView}
        onIngestComplete={onGraphUpdate}
        zoomIn={zoomIn}
        zoomOut={zoomOut}
        fitAll={fitAll}
        hasGraph={hasGraph}
      />

      <div className="relative min-h-0 flex-1">
        {view === "report" ? (
          <SentinelReportView threadId={threadId ?? null} />
        ) : !hasGraph ? (
          <div className="flex h-full w-full items-center justify-center text-muted-foreground">
            <p className="text-center text-base">
              Ingest the thread to see the graph.
            </p>
          </div>
        ) : (
          <>
            <InteractiveNvlWrapper
              ref={nvlRef}
              nodes={nvlNodes}
              rels={nvlRels}
              layout="hierarchical"
              nvlOptions={{ initialZoom: 2 }}
              nvlCallbacks={{
                onLayoutDone: () => {
                  nvlRef.current?.fit(nvlNodes.map((n) => n.id));
                },
              }}
              mouseEventCallbacks={{
                onPan: true,
                onDrag: false,
                onNodeClick: (n, _h, _e) => onNodeClick(n),
                onRelationshipClick: (r, _h, _e) => onRelationshipClick(r),
                onCanvasClick,
              }}
            />
            <GraphLegend />
            <MetadataPanel selected={selected} />
          </>
        )}
      </div>
    </div>
  );
}
