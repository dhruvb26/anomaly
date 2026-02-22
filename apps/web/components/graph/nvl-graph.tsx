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
import { useCallback, useRef, useState } from "react";
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
  const labelKey = (node.label ?? "").toString().toLowerCase();
  const typeKey = (node.type ?? "").toString().toLowerCase();
  return NODE_TYPE_COLORS[labelKey] ?? NODE_TYPE_COLORS[typeKey];
}

type SelectedItem =
  | { type: "node"; data: Record<string, unknown> }
  | { type: "edge"; data: Record<string, unknown> }
  | null;

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

function GraphToolbar({
  threadId,
  onIngestComplete,
  zoomIn,
  zoomOut,
  fitAll,
  hasGraph,
}: {
  threadId?: string;
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
    if (!API_URL) return;
    setClearing(true);
    try {
      const res = await fetch(`${API_URL}/ingest`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Clear failed: ${res.status}`);
      onIngestComplete?.();
    } catch (err) {
      console.error("Clear error:", err);
    } finally {
      setClearing(false);
    }
  }, [onIngestComplete]);

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
            tooltip="Clear"
            onClick={handleClear}
            disabled={clearing}
          >
            {clearing ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Trash2 className="h-5 w-5" />
            )}
          </ToolbarButton>
        </div>

        <div className="flex items-center gap-0.5">
          <ToolbarButton
            tooltip="Zoom in"
            onClick={zoomIn}
            disabled={!hasGraph}
          >
            <ZoomIn className="h-5 w-5" />
          </ToolbarButton>
          <ToolbarButton
            tooltip="Zoom out"
            onClick={zoomOut}
            disabled={!hasGraph}
          >
            <ZoomOut className="h-5 w-5" />
          </ToolbarButton>
          <ToolbarButton
            tooltip="Fit to screen"
            onClick={fitAll}
            disabled={!hasGraph}
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
        onIngestComplete={onGraphUpdate}
        zoomIn={zoomIn}
        zoomOut={zoomOut}
        fitAll={fitAll}
        hasGraph={hasGraph}
      />

      <div className="relative min-h-0 flex-1">
        {!hasGraph ? (
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
            <MetadataPanel selected={selected} />
          </>
        )}
      </div>
    </div>
  );
}
