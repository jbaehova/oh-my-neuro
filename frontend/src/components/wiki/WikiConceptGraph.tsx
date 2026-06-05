import { useMemo } from "react";
import { ChevronDown, ChevronUp, Network } from "lucide-react";

import { WikiGraph } from "@/lib/api";
import { cn } from "@/lib/utils";

type WikiConceptGraphProps = {
  graph: WikiGraph | null;
  selectedPageId?: string;
  expanded: boolean;
  onToggle: () => void;
  onSelectPage: (pageId: string) => void;
};

type LayoutNode = {
  id: string;
  label: string;
  fullLabel: string;
  kind: string;
  pageId: string;
  x: number;
  y: number;
  r: number;
};

const KIND_COLORS: Record<string, string> = {
  concept: "#2dd4bf",
  source: "#94a3b8",
  page: "#fbbf24",
};

export function WikiConceptGraph({
  graph,
  selectedPageId,
  expanded,
  onToggle,
  onSelectPage,
}: WikiConceptGraphProps) {
  const layout = useMemo(() => (graph ? buildLayout(graph, selectedPageId) : null), [graph, selectedPageId]);

  if (!graph || !layout || layout.nodes.length === 0) return null;

  const connected = layout.nodes.filter((n) => n.pageId !== selectedPageId).length;
  const compact = layout.nodes.length <= 3;

  return (
    <div className="border-b">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-secondary/50"
      >
        <div className="flex items-center gap-2 text-xs font-medium">
          <Network className="size-3.5 text-primary" />
          개념 그래프
          <span className="text-muted-foreground">· 연결 {connected}개</span>
        </div>
        {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            className={cn("w-full rounded-md border bg-muted/20 text-foreground", compact ? "h-32" : "h-40")}
            role="img"
            aria-label="개념 그래프"
          >
            {layout.edges.map((edge) => {
              const from = layout.nodes.find((n) => n.id === edge.source);
              const to = layout.nodes.find((n) => n.id === edge.target);
              if (!from || !to) return null;
              return (
                <line
                  key={`${edge.source}-${edge.target}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke="currentColor"
                  strokeOpacity={0.25}
                  strokeWidth={1.5}
                />
              );
            })}
            {layout.nodes.map((node) => {
              const selected = node.pageId === selectedPageId;
              const color = KIND_COLORS[node.kind] || KIND_COLORS.page;
              const label = truncate(node.label, compact ? 18 : 14);
              return (
                <g
                  key={node.id}
                  className="cursor-pointer"
                  onClick={() => onSelectPage(node.pageId)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") onSelectPage(node.pageId);
                  }}
                >
                  <title>{node.fullLabel}</title>
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={selected ? node.r + 2 : node.r}
                    fill={color}
                    stroke={selected ? "currentColor" : "transparent"}
                    strokeWidth={2}
                  />
                  <text
                    x={node.x}
                    y={node.y + node.r + 14}
                    textAnchor="middle"
                    fill="currentColor"
                    fontSize={10}
                    opacity={0.9}
                  >
                    {label}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
            <Legend color={KIND_COLORS.concept} label="개념" />
            <Legend color={KIND_COLORS.source} label="소스" />
            <Legend color={KIND_COLORS.page} label="페이지" />
          </div>
        </div>
      )}
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function buildLayout(graph: WikiGraph, focusPageId?: string) {
  const width = 400;
  const height = 160;
  const cx = width / 2;
  const focus = graph.nodes.find((n) => n.page_id === focusPageId);
  const focusNodeId = focus?.id;

  const related = new Set<string>();
  if (focusNodeId) {
    related.add(focusNodeId);
    for (const edge of graph.edges) {
      if (edge.source === focusNodeId) related.add(edge.target);
      if (edge.target === focusNodeId) related.add(edge.source);
    }
  }

  const nodes = graph.nodes.filter((n) => !focusNodeId || related.has(n.id));
  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));

  const layoutNodes: LayoutNode[] = [];
  const focusNode = nodes.find((n) => n.id === focusNodeId);
  const others = nodes.filter((n) => n.id !== focusNodeId);

  if (others.length <= 2) {
    const ordered = focusNode ? [focusNode, ...others] : others;
    const gap = ordered.length <= 2 ? 56 : 44;
    const startY = height / 2 - ((ordered.length - 1) * gap) / 2;
    ordered.forEach((node, index) => {
      layoutNodes.push({
        id: node.id,
        label: node.label,
        fullLabel: node.label,
        kind: node.kind,
        pageId: node.page_id,
        x: cx,
        y: startY + index * gap,
        r: node.kind === "concept" ? 12 : 9,
      });
    });
  } else if (focusNode) {
    layoutNodes.push({
      id: focusNode.id,
      label: focusNode.label,
      fullLabel: focusNode.label,
      kind: focusNode.kind,
      pageId: focusNode.page_id,
      x: cx,
      y: height / 2,
      r: focusNode.kind === "concept" ? 12 : 9,
    });
    const radius = Math.min(70, 28 + others.length * 8);
    others.forEach((node, index) => {
      const angle = (index / others.length) * Math.PI * 2 - Math.PI / 2;
      layoutNodes.push({
        id: node.id,
        label: node.label,
        fullLabel: node.label,
        kind: node.kind,
        pageId: node.page_id,
        x: cx + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
        r: node.kind === "concept" ? 11 : node.kind === "source" ? 8 : 9,
      });
    });
  } else {
    others.forEach((node, index) => {
      const angle = (index / Math.max(others.length, 1)) * Math.PI * 2 - Math.PI / 2;
      layoutNodes.push({
        id: node.id,
        label: node.label,
        fullLabel: node.label,
        kind: node.kind,
        pageId: node.page_id,
        x: cx + Math.cos(angle) * 50,
        y: height / 2 + Math.sin(angle) * 50,
        r: 9,
      });
    });
  }

  return { nodes: layoutNodes, edges, width, height };
}
