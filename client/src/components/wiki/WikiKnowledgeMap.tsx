import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import { Crosshair, Network, RotateCcw, ZoomOut } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { WikiGraph, WikiGraphNode } from "@/lib/api";

type WikiKnowledgeMapProps = {
  graph: WikiGraph | null;
  selectedPageId?: string;
  highlightedSources?: string[];
  onSelectPage: (pageId: string) => void;
  onOpenSource: (source: string) => void;
};

type GraphKind = WikiGraphNode["kind"];

type MapNode = {
  id: string;
  label: string;
  compactLabel: string;
  detailLabel: string;
  kind: GraphKind;
  pageId: string;
  sourcePath: string;
  degree: number;
  anchorX: number;
  anchorY: number;
  selected: boolean;
  highlighted: boolean;
  color: string;
  val: number;
};

type MapLink = {
  source: string;
  target: string;
  key: string;
  label: string;
  active: boolean;
  pulse: boolean;
  color: string;
  value: number;
};

type MapPayload = {
  nodes: MapNode[];
  links: MapLink[];
  totalSources: number;
  totalConcepts: number;
  totalPages: number;
};

type LabelBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const KIND_COLORS: Record<GraphKind, string> = {
  concept: "#2dd4bf",
  source: "#ff2f72",
  page: "#8b5cf6",
};

const KIND_LABELS: Record<GraphKind, string> = {
  source: "원본 문서",
  concept: "개념",
  page: "노트",
};

const DEFAULT_SIZE = { width: 1280, height: 720 };
const GRAPH_BACKGROUND = "#101113";
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const SOURCE_NOISE_TOKENS = new Set([
  "검토",
  "검토메모",
  "내용증명초안",
  "메모",
  "법령리서치",
  "사건요약",
  "상담기록",
  "소송전략메모",
  "의뢰인응대",
  "일정표",
  "초안",
  "형사상담메모",
]);
const SHORT_DOMAIN_TOKENS = new Set([
  "cctv",
  "cto",
  "sop",
  "개인정보",
  "공연성",
  "공정성",
  "대항력",
  "채권",
  "채무",
  "민법",
  "산재",
  "소장",
  "형법",
  "헌법",
]);
const DOMAIN_HINTS = [
  "개인정보",
  "공동창업",
  "대항력",
  "명예훼손",
  "민법",
  "비밀유지",
  "산재",
  "손해배상",
  "우선변제",
  "이해상충",
  "임대차",
  "재판",
  "정보통신망",
  "주주간",
  "지급명령",
  "채권",
  "채무",
  "헌법",
  "형법",
];

function initialCanvasSize() {
  if (typeof window === "undefined") return DEFAULT_SIZE;
  const sidebar = window.innerWidth >= 1024 ? 256 : 0;
  const horizontalPadding = window.innerWidth >= 1024 ? 66 : window.innerWidth >= 640 ? 50 : 34;
  const width = Math.max(360, window.innerWidth - sidebar - horizontalPadding);
  return { width, height: canvasHeight(width) };
}

function canvasHeight(width: number) {
  return Math.max(640, Math.min(820, Math.floor(width * 0.52)));
}

export function WikiKnowledgeMap({
  graph,
  selectedPageId,
  highlightedSources = [],
  onSelectPage,
  onOpenSource,
}: WikiKnowledgeMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraphMethods<MapNode, MapLink> | undefined>(undefined);
  const labelBoxesRef = useRef<LabelBox[]>([]);
  const [size, setSize] = useState(initialCanvasSize);
  const [hoveredNode, setHoveredNode] = useState<MapNode | null>(null);
  const canvasSize = size;
  const highlightedSet = useMemo(() => new Set(highlightedSources), [highlightedSources]);
  const payload = useMemo(
    () => buildPayload(graph, selectedPageId, highlightedSet),
    [graph, highlightedSet, selectedPageId],
  );
  const active = useMemo(() => buildActiveSets(payload, hoveredNode), [hoveredNode, payload]);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const resize = () => {
      const width = Math.max(360, Math.floor(element.clientWidth || element.getBoundingClientRect().width));
      const height = canvasHeight(width);
      setSize((current) => {
        if (current?.width === width && current.height === height) return current;
        return { width, height };
      });
    };
    const frame = window.requestAnimationFrame(resize);
    const timers = [window.setTimeout(resize, 80), window.setTimeout(resize, 360)];
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    window.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("resize", resize);
    return () => {
      window.cancelAnimationFrame(frame);
      timers.forEach((timer) => window.clearTimeout(timer));
      observer.disconnect();
      window.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("resize", resize);
    };
  }, []);

  useEffect(() => {
    const graphInstance = graphRef.current;
    if (!graphInstance || payload.nodes.length === 0) return;
    window.setTimeout(() => graphInstance.zoomToFit(900, wideFitPadding(size)), 140);
  }, [payload.links.length, payload.nodes.length, size]);

  useEffect(() => {
    const graphInstance = graphRef.current;
    if (!graphInstance || payload.nodes.length === 0) return;
    const charge = graphInstance.d3Force("charge") as ForceWithStrength<MapNode> | undefined;
    charge?.strength?.((node) => {
      if (node.kind === "source") return -150;
      if (node.kind === "concept") return -34;
      return -74;
    });
    const link = graphInstance.d3Force("link") as ForceWithDistance<MapNode, MapLink> | undefined;
    link?.distance?.((edge) => {
      if (edge.label === "summarized") return 44;
      if (edge.active) return 64;
      return 56;
    });
    graphInstance.d3Force("cluster", createClusterForce());
    graphInstance.d3ReheatSimulation();
  }, [payload.nodes.length, payload.links.length, size]);

  const drawBackdrop = useCallback(
    (ctx: CanvasRenderingContext2D) => {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      const width = ctx.canvas.width;
      const height = ctx.canvas.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = GRAPH_BACKGROUND;
      ctx.fillRect(0, 0, width, height);
      labelBoxesRef.current = [];
      ctx.restore();
    },
    [],
  );

  const drawNode = useCallback(
    (rawNode: NodeObject<MapNode>, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const node = rawNode as NodeObject<MapNode> & MapNode;
      const isHot = active.nodeIds.has(node.id);
      const radius = nodeRadius(node);
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      ctx.save();
      const haloRadius = (isHot ? radius + 28 : radius + 16) / Math.max(0.8, globalScale * 0.55);
      const halo = ctx.createRadialGradient(x, y, radius * 0.4, x, y, haloRadius);
      halo.addColorStop(0, hexToRgba(node.color, isHot ? 0.34 : 0.15));
      halo.addColorStop(0.42, hexToRgba(node.color, isHot ? 0.14 : 0.055));
      halo.addColorStop(1, hexToRgba(node.color, 0));
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(x, y, haloRadius, 0, Math.PI * 2);
      ctx.fill();

      ctx.shadowColor = hexToRgba(node.color, isHot ? 0.72 : 0.38);
      ctx.shadowBlur = isHot ? 18 : 9;
      ctx.beginPath();
      ctx.fillStyle = node.color;
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = (node.selected || node.highlighted ? 2.5 : 1.1) / globalScale;
      ctx.strokeStyle = node.selected || node.highlighted ? "rgba(255,255,255,0.92)" : "rgba(255,255,255,0.58)";
      ctx.stroke();

      const screenPosition = graphRef.current?.graph2ScreenCoords(x, y);
      const label = labelForNode(node, isHot, globalScale);
      if (label && screenPosition) {
        const screenFontSize = isHot ? 12.5 : node.kind === "source" ? 11.2 : 10.4;
        const fontSize = screenFontSize / globalScale;
        ctx.font = `${isHot ? 700 : 600} ${fontSize}px Inter, ui-sans-serif, system-ui`;
        const graphTextWidth = ctx.measureText(label).width;
        const textAlign = node.kind === "source" ? "left" : "center";
        const labelX = node.kind === "source" ? x + radius + 8 / globalScale : x;
        const labelY = y + (node.kind === "source" ? 0 : radius + 10 / globalScale);
        const screenLabelX = screenPosition.x + (labelX - x) * globalScale;
        const screenLabelY = screenPosition.y + (labelY - y) * globalScale;
        const screenWidth = graphTextWidth * globalScale;
        const screenHeight = screenFontSize * 1.32;
        const box = {
          x: textAlign === "left" ? screenLabelX : screenLabelX - screenWidth / 2,
          y: screenLabelY - screenHeight / 2,
          width: screenWidth,
          height: screenHeight,
        };
        const canDrawLabel =
          isHot ||
          node.selected ||
          node.highlighted ||
          reserveLabel(labelBoxesRef.current, box, canvasSize.width, canvasSize.height);
        if (!canDrawLabel) {
          ctx.restore();
          return;
        }
        ctx.fillStyle = isHot ? "#ffffff" : "rgba(232, 238, 247, 0.76)";
        ctx.shadowColor = "rgba(0,0,0,0.9)";
        ctx.shadowBlur = 4 / globalScale;
        ctx.shadowOffsetY = 1 / globalScale;
        ctx.textAlign = textAlign;
        ctx.textBaseline = "middle";
        ctx.fillText(label, labelX, labelY);
      }
      ctx.restore();
    },
    [active.nodeIds, canvasSize.height, canvasSize.width],
  );

  const paintPointerArea = useCallback((rawNode: NodeObject<MapNode>, color: string, ctx: CanvasRenderingContext2D) => {
    const node = rawNode as NodeObject<MapNode> & MapNode;
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, nodeRadius(node) + 16, 0, Math.PI * 2);
    ctx.fill();
  }, []);

  function fitGraph() {
    graphRef.current?.zoomToFit(900, fitPadding(canvasSize));
  }

  function wideGraph() {
    graphRef.current?.zoomToFit(900, wideFitPadding(canvasSize));
  }

  function reheatGraph() {
    graphRef.current?.d3ReheatSimulation();
    window.setTimeout(wideGraph, 260);
  }

  function activateNode(node: NodeObject<MapNode> & MapNode) {
    if (node.sourcePath) {
      onOpenSource(node.sourcePath);
      return;
    }
    if (node.pageId) onSelectPage(node.pageId);
  }

  if (!payload.nodes.length) {
    return (
      <section className="wiki-graph-shell overflow-hidden rounded-lg">
        <div className="flex items-center gap-2 border-b px-4 py-3 text-sm font-medium">
          <Network className="size-4 text-primary" />
          문서 관계 비주얼
        </div>
        <div className="grid min-h-[420px] place-items-center px-6 text-center text-sm text-muted-foreground">
          Rebuild 후 문서 관계도가 표시됩니다.
        </div>
      </section>
    );
  }

  return (
    <section className="wiki-graph-shell overflow-hidden rounded-lg">
      <div className="flex flex-col gap-4 border-b border-white/10 bg-[#151517] px-5 py-4 text-slate-50 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-md bg-white/[0.06] text-rose-200 ring-1 ring-white/10">
            <Network className="size-4" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold">문서 관계 비주얼</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-300">
              <span>{payload.nodes.length} nodes</span>
              <span>{payload.links.length} links</span>
              <span>{highlightedSources.length} easy-index focus</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Legend kind="source" count={payload.totalSources} />
          <Legend kind="concept" count={payload.totalConcepts} />
          <Legend kind="page" count={payload.totalPages} />
          <Button
            size="sm"
            variant="outline"
            className="border-white/15 bg-white/[0.06] text-slate-100 hover:bg-white/10"
            onClick={fitGraph}
            title="관계도 맞춤"
          >
            <Crosshair className="size-4" />
            Fit
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-white/15 bg-white/[0.06] text-slate-100 hover:bg-white/10"
            onClick={wideGraph}
            title="더 멀리 보기"
          >
            <ZoomOut className="size-4" />
            Wide
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-white/15 bg-white/[0.06] text-slate-100 hover:bg-white/10"
            onClick={reheatGraph}
            title="시뮬레이션 재정렬"
          >
            <RotateCcw className="size-4" />
            Reflow
          </Button>
        </div>
      </div>
      <div
        ref={containerRef}
        className="wiki-graph-frame relative min-h-[640px] w-full overflow-hidden"
        style={{ height: canvasSize.height }}
      >
        <ForceGraph2D<MapNode, MapLink>
          key={`${canvasSize.width}x${canvasSize.height}`}
          ref={graphRef}
          graphData={payload}
          width={canvasSize.width}
          height={canvasSize.height}
          backgroundColor="rgba(0,0,0,0)"
          nodeId="id"
          nodeVal="val"
          nodeLabel={(node) => `${KIND_LABELS[node.kind]} · ${node.sourcePath || node.pageId || node.detailLabel}`}
          nodeColor={(node) => node.color}
          nodeCanvasObject={drawNode}
          nodePointerAreaPaint={paintPointerArea}
          linkColor={(link) => {
            if (active.linkKeys.has(link.key) || link.active) return hexToRgba(link.color, 0.68);
            return hexToRgba(link.color, 0.22);
          }}
          linkWidth={(link) => (active.linkKeys.has(link.key) || link.active ? 1.6 : 0.55)}
          linkDirectionalParticles={(link) => (active.linkKeys.has(link.key) || link.active ? 3 : link.pulse ? 1 : 0)}
          linkDirectionalParticleWidth={(link) => (active.linkKeys.has(link.key) || link.active ? 2.2 : 0.9)}
          linkDirectionalParticleSpeed={(link) => (active.linkKeys.has(link.key) || link.active ? 0.009 : 0.003)}
          linkDirectionalParticleColor={(link) => link.color}
          onRenderFramePre={drawBackdrop}
          onNodeHover={(node) => setHoveredNode((node as NodeObject<MapNode> & MapNode) ?? null)}
          onNodeClick={(node) => activateNode(node as NodeObject<MapNode> & MapNode)}
          onEngineStop={fitGraph}
          cooldownTicks={120}
          d3AlphaDecay={0.032}
          d3VelocityDecay={0.36}
          minZoom={0.02}
          maxZoom={6}
          autoPauseRedraw={false}
          showPointerCursor
        />
        {hoveredNode ? (
          <div className="pointer-events-none absolute bottom-4 left-4 max-w-[420px] rounded-md border border-white/10 bg-[#151517]/90 px-3 py-2 text-slate-100 shadow-xl shadow-black/30 backdrop-blur">
            <div className="flex items-center gap-2">
              <span className="size-2.5 rounded-full" style={{ background: hoveredNode.color }} />
              <span className="truncate text-sm font-semibold">{hoveredNode.detailLabel}</span>
              <Badge variant="outline" className="border-white/15 bg-white/[0.06] text-slate-100">
                {KIND_LABELS[hoveredNode.kind]}
              </Badge>
            </div>
            <div className="mt-1 truncate text-xs text-slate-400">
              {hoveredNode.sourcePath || hoveredNode.pageId}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Legend({ kind, count }: { kind: GraphKind; count: number }) {
  return (
    <Badge variant="outline" className="gap-1.5 border-white/15 bg-white/[0.06] text-slate-100">
      <span className="size-2 rounded-full" style={{ background: KIND_COLORS[kind] }} />
      {KIND_LABELS[kind]} {count}
    </Badge>
  );
}

function buildPayload(graph: WikiGraph | null, selectedPageId: string | undefined, highlightedSources: Set<string>): MapPayload {
  if (!graph || graph.nodes.length === 0) {
    return { nodes: [], links: [], totalSources: 0, totalConcepts: 0, totalPages: 0 };
  }

  const rawNodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const sourceIds = graph.nodes.filter((node) => node.kind === "source").map((node) => node.id);
  const sourceOrder = new Map(sourceIds.map((id, index) => [id, index]));
  const anchorByNode = new Map<string, string>();
  const degree = new Map<string, number>();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    const from = rawNodeById.get(edge.source);
    const to = rawNodeById.get(edge.target);
    if (from?.kind === "source") {
      anchorByNode.set(edge.target, edge.source);
    }
    if (to?.kind === "source") {
      anchorByNode.set(edge.source, edge.target);
    }
  }

  const totals = {
    totalSources: graph.nodes.filter((node) => node.kind === "source").length,
    totalConcepts: graph.nodes.filter((node) => node.kind === "concept").length,
    totalPages: graph.nodes.filter((node) => node.kind === "page").length,
  };

  const localIndexBySource = new Map<string, number>();
  const nodes = graph.nodes.map((node, index) => {
    const nodeDegree = degree.get(node.id) ?? 0;
    const selected = Boolean(selectedPageId && node.page_id === selectedPageId);
    const highlighted = Boolean(node.source_path && highlightedSources.has(node.source_path));
    const anchorSource = node.kind === "source" ? node.id : anchorByNode.get(node.id) || "";
    const sourceIndex = sourceOrder.get(anchorSource) ?? index % Math.max(1, sourceIds.length);
    const localKey = anchorSource || "unlinked";
    const localIndex = localIndexBySource.get(localKey) ?? 0;
    localIndexBySource.set(localKey, localIndex + 1);
    const seed = seededPosition(index, node.kind, sourceIndex, Math.max(1, sourceIds.length), localIndex);
    const detailLabel = node.source_path ? lastPathPart(node.source_path) : node.label;
    return {
      id: node.id,
      label: node.label,
      compactLabel: smartGraphLabel(node.label, node.kind),
      detailLabel,
      kind: node.kind,
      pageId: node.page_id,
      sourcePath: node.source_path || "",
      degree: nodeDegree,
      anchorX: seed.anchorX,
      anchorY: seed.anchorY,
      selected,
      highlighted,
      color: KIND_COLORS[node.kind],
      val: nodeValue(node.kind, nodeDegree, selected, highlighted),
      x: seed.x,
      y: seed.y,
    };
  });
  nodes.sort((left, right) => labelPriority(right) - labelPriority(left));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  const links = graph.edges
    .filter((edge) => nodeById.has(edge.source) && nodeById.has(edge.target))
    .map((edge, index) => {
      const from = nodeById.get(edge.source);
      const to = nodeById.get(edge.target);
      const active = Boolean(from?.selected || from?.highlighted || to?.selected || to?.highlighted);
      return {
        source: edge.source,
        target: edge.target,
        key: `${edge.source}->${edge.target}:${index}`,
        label: edge.label || "",
        active,
        pulse: index % 5 === 0,
        color: edgeColor(from, to),
        value: active ? 2.2 : 1,
      };
    });

  return { nodes, links, ...totals };
}

function buildActiveSets(payload: MapPayload, hoveredNode: MapNode | null) {
  const nodeIds = new Set<string>();
  const linkKeys = new Set<string>();
  for (const node of payload.nodes) {
    if (node.selected || node.highlighted) nodeIds.add(node.id);
  }
  if (hoveredNode) nodeIds.add(hoveredNode.id);

  for (const link of payload.links) {
    const sourceId = nodeId(link.source);
    const targetId = nodeId(link.target);
    if (link.active || sourceId === hoveredNode?.id || targetId === hoveredNode?.id) {
      linkKeys.add(link.key);
      if (sourceId) nodeIds.add(sourceId);
      if (targetId) nodeIds.add(targetId);
    }
  }
  return { nodeIds, linkKeys };
}

function nodeId(value: string | number | NodeObject<MapNode> | undefined) {
  if (value == null) return "";
  if (typeof value === "object") return String(value.id ?? "");
  return String(value);
}

function nodeValue(kind: GraphKind, degree: number, selected: boolean, highlighted: boolean) {
  const base = kind === "source" ? 6.8 : kind === "concept" ? 3.6 : 4.6;
  const emphasis = selected || highlighted ? 4.2 : 0;
  return base + Math.sqrt(Math.max(1, degree)) * 1.55 + emphasis;
}

function nodeRadius(node: MapNode) {
  const base = node.kind === "source" ? 5.8 : node.kind === "concept" ? 3.5 : 4.4;
  return base + Math.sqrt(Math.max(1, node.degree)) * 0.82 + (node.selected || node.highlighted ? 2.2 : 0);
}

function seededPosition(index: number, kind: GraphKind, sourceIndex: number, sourceCount: number, localIndex: number) {
  const clusterAngle = sourceIndex * GOLDEN_ANGLE;
  const clusterRadius = 96 + Math.sqrt(sourceIndex + 1) / Math.sqrt(sourceCount) * 520;
  const anchorX = Math.cos(clusterAngle) * clusterRadius * 1.28;
  const anchorY = Math.sin(clusterAngle) * clusterRadius * 0.72;
  const localAngle = (localIndex + 1) * GOLDEN_ANGLE + index * 0.17;
  const localRadius =
    kind === "source" ? 0 : kind === "page" ? 28 + (localIndex % 3) * 9 : 44 + Math.sqrt(localIndex + 1) * 11;
  return {
    anchorX,
    anchorY,
    x: anchorX + Math.cos(localAngle) * localRadius,
    y: anchorY + Math.sin(localAngle) * localRadius,
  };
}

function edgeColor(from: MapNode | undefined, to: MapNode | undefined) {
  if (from?.highlighted || to?.highlighted || from?.selected || to?.selected) return "#fbbf24";
  if (from?.kind === "source" || to?.kind === "source") return KIND_COLORS.source;
  if (from?.kind === "page" || to?.kind === "page") return KIND_COLORS.page;
  return KIND_COLORS.concept;
}

function fitPadding(size: { width: number; height: number }) {
  return Math.max(130, Math.min(size.width, size.height) * 0.16);
}

function wideFitPadding(size: { width: number; height: number }) {
  return Math.max(280, Math.min(size.width, size.height) * 0.34);
}

function labelForNode(node: MapNode, isHot: boolean, globalScale: number) {
  if (isHot) return truncateMiddle(node.detailLabel, 34);
  if (node.selected || node.highlighted) return node.compactLabel;
  if (node.kind === "source") {
    if (globalScale < 0.18 && node.degree < 7) return "";
    return node.compactLabel;
  }
  if (node.kind === "concept" && globalScale > 1.18 && node.degree >= 3) return node.compactLabel;
  if (node.kind === "page" && globalScale > 1.05 && node.degree >= 2) return node.compactLabel;
  return "";
}

function reserveLabel(boxes: LabelBox[], nextBox: LabelBox, width: number, height: number) {
  const padding = 7;
  const box = {
    x: nextBox.x - padding,
    y: nextBox.y - padding,
    width: nextBox.width + padding * 2,
    height: nextBox.height + padding * 2,
  };
  if (box.x < 16 || box.y < 16 || box.x + box.width > width - 16 || box.y + box.height > height - 16) {
    return false;
  }
  for (const current of boxes) {
    if (boxesOverlap(current, box)) return false;
  }
  boxes.push(box);
  return true;
}

function boxesOverlap(left: LabelBox, right: LabelBox) {
  return (
    left.x < right.x + right.width &&
    left.x + left.width > right.x &&
    left.y < right.y + right.height &&
    left.y + left.height > right.y
  );
}

function smartGraphLabel(label: string, kind: GraphKind) {
  if (kind !== "source") return truncateEnd(cleanLabel(label), kind === "concept" ? 16 : 18);
  const tokens = tokenizeSourceLabel(label);
  if (!tokens.length) return truncateEnd(cleanLabel(label), 18);

  const ranked = tokens
    .map((token, index) => ({ token, index, score: scoreSourceToken(token, index) }))
    .filter((item) => item.score > 0.5)
    .sort((left, right) => right.score - left.score || left.index - right.index);

  const picked: string[] = [];
  for (const item of ranked) {
    if (picked.includes(item.token)) continue;
    const nextLength = [...picked, item.token].join(" · ").length;
    if (picked.length > 0 && nextLength > 19) continue;
    picked.push(item.token);
    if (picked.length >= 2 || nextLength >= 13) break;
  }

  const fallback = tokens.filter((token) => !SOURCE_NOISE_TOKENS.has(token.toLowerCase())).slice(0, 2);
  const output = picked.length ? picked : fallback;
  return truncateEnd(output.join(" · ") || cleanLabel(label), 20);
}

function tokenizeSourceLabel(label: string) {
  const basename = cleanLabel(lastPathPart(label))
    .replace(/\.[a-z0-9]{1,8}$/i, "")
    .replace(/\b\d{4}[-_.년 ]?\d{1,2}[-_.월 ]?\d{1,2}일?\b/g, " ")
    .replace(/\b\d{1,2}[-_.]\d{1,2}\b/g, " ")
    .replace(/\b20\d{2}\b/g, " ")
    .replace(/[()[\]{}]/g, " ");
  return basename
    .split(/[\s_.\-·,]+/u)
    .map((token) => token.trim().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ""))
    .filter((token) => token.length > 0 && !/^\d+$/.test(token) && !/^(md|pdf|docx?|txt)$/i.test(token));
}

function scoreSourceToken(token: string, index: number) {
  const lower = token.toLowerCase();
  let score = 0;
  if (SOURCE_NOISE_TOKENS.has(lower)) score -= 5;
  if (looksLikeNameCandidate(token)) score -= 8;
  if (SHORT_DOMAIN_TOKENS.has(lower)) score += 4;
  if (DOMAIN_HINTS.some((hint) => lower.includes(hint.toLowerCase()))) score += 4;
  if (/[가-힣]/.test(token)) score += 1;
  if (token.length >= 4 && token.length <= 12) score += 1.5;
  if (token.length > 14) score -= 1.2;
  if (index < 4) score += 0.4;
  return score;
}

function looksLikeNameCandidate(token: string) {
  const lower = token.toLowerCase();
  return /^[가-힣]{2,3}$/.test(token) && !SHORT_DOMAIN_TOKENS.has(lower) && !SOURCE_NOISE_TOKENS.has(lower);
}

function labelPriority(node: MapNode) {
  if (node.selected || node.highlighted) return 1000 + node.degree;
  if (node.kind === "source") return 500 + node.degree;
  if (node.kind === "concept") return 80 + node.degree;
  return 40 + node.degree;
}

function lastPathPart(value: string) {
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function cleanLabel(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function truncateEnd(value: string, max: number) {
  const chars = Array.from(value);
  if (chars.length <= max) return value;
  return `${chars.slice(0, Math.max(1, max - 1)).join("")}…`;
}

function truncateMiddle(value: string, max: number) {
  if (value.length <= max) return value;
  const head = Math.ceil((max - 1) * 0.62);
  const tail = Math.max(4, max - head - 1);
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function hexToRgba(hex: string, alpha: number) {
  const parsed = hex.replace("#", "");
  const r = Number.parseInt(parsed.slice(0, 2), 16);
  const g = Number.parseInt(parsed.slice(2, 4), 16);
  const b = Number.parseInt(parsed.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

type ForceWithStrength<NodeType> = {
  strength?: (value: number | ((node: NodeObject<NodeType> & NodeType) => number)) => unknown;
};

type ForceWithDistance<NodeType, LinkType> = {
  distance?: (value: number | ((link: LinkObject<NodeType, LinkType> & LinkType) => number)) => unknown;
};

type SimNode = NodeObject<MapNode> &
  MapNode & {
    x?: number;
    y?: number;
    vx?: number;
    vy?: number;
  };

type ClusterForce = ((alpha: number) => void) & {
  initialize?: (nodes: SimNode[]) => void;
};

function createClusterForce(): ClusterForce {
  let nodes: SimNode[] = [];
  const force = ((alpha: number) => {
    const strength = 0.038 * alpha;
    for (const node of nodes) {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const pull = node.kind === "source" ? strength * 1.18 : strength;
      node.vx = (node.vx ?? 0) + (node.anchorX - x) * pull;
      node.vy = (node.vy ?? 0) + (node.anchorY - y) * pull;
    }
  }) as ClusterForce;
  force.initialize = (nextNodes) => {
    nodes = nextNodes;
  };
  return force;
}
