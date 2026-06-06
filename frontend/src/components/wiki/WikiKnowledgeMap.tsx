import { useMemo } from "react";
import { FileText, Network } from "lucide-react";

import type { WikiGraph, WikiGraphNode } from "@/lib/api";

type WikiKnowledgeMapProps = {
  graph: WikiGraph | null;
  selectedPageId?: string;
  highlightedSources?: string[];
  onSelectPage: (pageId: string) => void;
  onOpenSource: (source: string) => void;
};

type LayoutNode = {
  id: string;
  label: string;
  kind: WikiGraphNode["kind"];
  pageId: string;
  sourcePath: string;
  x: number;
  y: number;
  r: number;
  selected: boolean;
  highlighted: boolean;
};

const KIND_COLORS: Record<WikiGraphNode["kind"], string> = {
  concept: "#14b8a6",
  source: "#64748b",
  page: "#f59e0b",
};

const MAX_VISIBLE_NODES = 88;

export function WikiKnowledgeMap({
  graph,
  selectedPageId,
  highlightedSources = [],
  onSelectPage,
  onOpenSource,
}: WikiKnowledgeMapProps) {
  const layout = useMemo(
    () => buildLayout(graph, selectedPageId, highlightedSources),
    [graph, highlightedSources, selectedPageId],
  );

  if (!layout || layout.nodes.length === 0) {
    return (
      <section className="surface overflow-hidden rounded-lg">
        <div className="flex items-center gap-2 border-b px-4 py-3 text-sm font-medium">
          <Network className="size-4 text-primary" />
          문서 관계
        </div>
        <div className="grid min-h-[260px] place-items-center px-6 text-center text-sm text-muted-foreground">
          Rebuild 후 문서 관계도가 표시됩니다.
        </div>
      </section>
    );
  }

  function activate(node: LayoutNode) {
    if (node.kind === "source" && node.sourcePath) {
      onOpenSource(node.sourcePath);
      return;
    }
    if (node.pageId) onSelectPage(node.pageId);
  }

  return (
    <section className="surface overflow-hidden rounded-lg">
      <div className="flex flex-col gap-2 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <Network className="size-4 text-primary" />
          <div className="min-w-0">
            <div className="text-sm font-semibold">문서 관계 비주얼</div>
            <div className="truncate text-xs text-muted-foreground">
              {layout.totalNodes} nodes · {layout.totalEdges} links
              {layout.hiddenNodes > 0 ? ` · ${layout.hiddenNodes} hidden` : ""}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-3 text-[11px] text-muted-foreground">
          <Legend color={KIND_COLORS.source} label="원본 문서" />
          <Legend color={KIND_COLORS.concept} label="개념" />
          <Legend color={KIND_COLORS.page} label="노트" />
        </div>
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="h-[330px] w-full bg-background text-foreground sm:h-[390px]"
          role="img"
          aria-label="문서와 개념 관계도"
        >
          <defs>
            <radialGradient id="wiki-map-wash" cx="50%" cy="50%" r="68%">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.06" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect width={layout.width} height={layout.height} fill="url(#wiki-map-wash)" />
          {layout.edges.map((edge) => {
            const from = layout.nodesById.get(edge.source);
            const to = layout.nodesById.get(edge.target);
            if (!from || !to) return null;
            const active = from.selected || to.selected || from.highlighted || to.highlighted;
            return (
              <line
                key={`${edge.source}-${edge.target}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="currentColor"
                strokeOpacity={active ? 0.36 : 0.16}
                strokeWidth={active ? 2 : 1}
              />
            );
          })}
          {layout.nodes.map((node) => {
            const color = KIND_COLORS[node.kind];
            return (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                className="cursor-pointer outline-none"
                onClick={() => activate(node)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") activate(node);
                }}
              >
                <title>{node.sourcePath || node.label}</title>
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={node.highlighted ? node.r + 7 : node.r + 4}
                  fill={color}
                  opacity={node.highlighted ? 0.14 : node.selected ? 0.16 : 0.08}
                />
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={node.selected ? node.r + 2 : node.r}
                  fill={color}
                  stroke={node.selected || node.highlighted ? "currentColor" : "hsl(var(--background))"}
                  strokeWidth={node.selected || node.highlighted ? 2.2 : 1.4}
                />
                <text
                  x={node.x}
                  y={node.y + node.r + 16}
                  textAnchor="middle"
                  fill="currentColor"
                  fontSize={11}
                  opacity={node.selected || node.highlighted ? 0.98 : 0.72}
                  fontWeight={node.selected || node.highlighted ? 600 : 500}
                >
                  {truncate(node.label, node.kind === "concept" ? 20 : 16)}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="pointer-events-none absolute left-4 top-4 hidden max-w-[240px] rounded-md border bg-background/85 px-3 py-2 text-xs leading-5 text-muted-foreground shadow-sm backdrop-blur sm:block">
          <div className="flex items-center gap-1.5 font-medium text-foreground">
            <FileText className="size-3.5" />
            {highlightedSources.length > 0 ? "Easy index 결과 강조" : "노드 클릭"}
          </div>
          <div className="mt-1">
            원본 문서는 파일을 열고, 개념과 노트는 문서 노트를 표시합니다.
          </div>
        </div>
      </div>
    </section>
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

function buildLayout(graph: WikiGraph | null, selectedPageId?: string, highlightedSources: string[] = []) {
  if (!graph || graph.nodes.length === 0) return null;

  const highlighted = new Set(highlightedSources);
  const degree = new Map<string, number>();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  const required = new Set<string>();
  for (const node of graph.nodes) {
    if (node.page_id === selectedPageId) required.add(node.id);
    if (node.source_path && highlighted.has(node.source_path)) required.add(node.id);
  }
  for (const edge of graph.edges) {
    if (required.has(edge.source)) required.add(edge.target);
    if (required.has(edge.target)) required.add(edge.source);
  }

  const visibleNodes = [...graph.nodes]
    .sort((a, b) => {
      const requiredDelta = Number(required.has(b.id)) - Number(required.has(a.id));
      if (requiredDelta !== 0) return requiredDelta;
      const pageDelta = Number(a.kind === "page") - Number(b.kind === "page");
      if (pageDelta !== 0) return pageDelta;
      return (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0);
    })
    .slice(0, MAX_VISIBLE_NODES);
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const edges = graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));

  const width = 900;
  const height = 420;
  const cx = width / 2;
  const cy = height / 2;
  const focus =
    visibleNodes.find((node) => node.kind === "source" && node.page_id === selectedPageId) ??
    visibleNodes.find((node) => node.page_id === selectedPageId);
  const nodes: LayoutNode[] = [];

  if (focus) {
    nodes.push(toLayoutNode(focus, cx, cy, 18, selectedPageId, highlighted));
  }

  const rest = visibleNodes.filter((node) => node.id !== focus?.id);
  placeRing(rest.filter((node) => node.kind === "concept"), 116, -Math.PI / 2);
  placeRing(rest.filter((node) => node.kind === "source"), 176, Math.PI / 2);
  placeRail(rest.filter((node) => node.kind === "page"));

  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  return {
    nodes,
    nodesById,
    edges,
    width,
    height,
    totalNodes: graph.nodes.length,
    totalEdges: graph.edges.length,
    hiddenNodes: Math.max(0, graph.nodes.length - visibleNodes.length),
  };

  function placeRing(items: WikiGraphNode[], radius: number, startAngle: number) {
    if (items.length === 0) return;
    items.forEach((node, index) => {
      const angle = startAngle + (index / items.length) * Math.PI * 2;
      nodes.push(
        toLayoutNode(
          node,
          cx + Math.cos(angle) * radius,
          cy + Math.sin(angle) * radius * 0.78,
          node.kind === "concept" ? 13 : 11,
          selectedPageId,
          highlighted,
        ),
      );
    });
  }

  function placeRail(items: WikiGraphNode[]) {
    if (items.length === 0) return;
    const gap = width / (items.length + 1);
    items.forEach((node, index) => {
      nodes.push(toLayoutNode(node, gap * (index + 1), height - 48, 9, selectedPageId, highlighted));
    });
  }
}

function toLayoutNode(
  node: WikiGraphNode,
  x: number,
  y: number,
  r: number,
  selectedPageId: string | undefined,
  highlightedSources: Set<string>,
): LayoutNode {
  return {
    id: node.id,
    label: node.label,
    kind: node.kind,
    pageId: node.page_id,
    sourcePath: node.source_path || "",
    x,
    y,
    r,
    selected: Boolean(selectedPageId && node.page_id === selectedPageId),
    highlighted: Boolean(node.source_path && highlightedSources.has(node.source_path)),
  };
}

function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
