"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import type { GraphResponse } from "@/lib/api/schemas";
import {
  acousticColor,
  GREY_NODE,
  oklchString,
  selectionRing,
} from "@/lib/color/acoustic";
import { GraphHoverCard } from "./hover-card";

/** Node payload carried through the force simulation. */
interface MapNodeData {
  id: number;
  name: string;
  trackCount: number;
  /** Resolved oklch() fill — acoustic mapping, or the grey unknown state. */
  fill: string;
  /** Selection-ring color: own color at L+0.12, chroma re-clamped. */
  ring: string;
  grey: boolean;
  /** True when this playlist is a subset of another — permanent satellite ring. */
  isSubset: boolean;
}

interface MapLinkData {
  shared: number;
  subset: boolean;
}

type MapNode = NodeObject<MapNodeData>;
type MapLink = LinkObject<MapNodeData, MapLinkData>;

/** Track count → radius, sqrt scale (graph rendering spec §1). */
export function nodeRadius(trackCount: number): number {
  return Math.min(30, Math.max(7, 4 + 1.5 * Math.sqrt(trackCount)));
}

/** Shared-track count → edge width (graph rendering spec §3). */
export function edgeWidth(shared: number): number {
  return 0.75 + 2.25 * Math.min(1, shared / 40);
}

const LABEL_THRESHOLD_PX = 8;
const LABEL_FADE_MS = 150;
const HOVER_CARD_DELAY_MS = 220;

/** Design-token colors the canvas painter needs, resolved from CSS once. */
interface CanvasTokens {
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  borderSubtle: string;
  borderStrong: string;
  fontText: string;
}

function readCanvasTokens(): CanvasTokens {
  const style = getComputedStyle(document.documentElement);
  const v = (name: string) => style.getPropertyValue(name).trim();
  return {
    textPrimary: v("--text-primary"),
    textSecondary: v("--text-secondary"),
    textMuted: v("--text-muted"),
    borderSubtle: v("--border-subtle"),
    borderStrong: v("--border-strong"),
    fontText: v("--font-b612") || "sans-serif",
  };
}

interface GraphCanvasProps {
  graph: GraphResponse;
  selectedId: number | null;
  onSelect: (playlistId: number | null) => void;
  /** Right-click on a node — opens the map context menu at screen coords. */
  onNodeContextMenu?: (playlistId: number, x: number, y: number) => void;
  /** Right-dock width in px — fit and camera moves respect the inset. */
  rightInset: number;
  reducedMotion: boolean;
}

export default function GraphCanvas({
  graph,
  selectedId,
  onSelect,
  onNodeContextMenu,
  rightInset,
  reducedMotion,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods<MapNode, MapLink> | undefined>(
    undefined,
  );
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [tokens, setTokens] = useState<CanvasTokens | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [hoverCard, setHoverCard] = useState<{
    nodeId: number;
    x: number;
    y: number;
  } | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Per-frame label bookkeeping: fade alphas and collision rects.
  const labelAlpha = useRef(new Map<number, number>());
  const lastFrameAt = useRef(0);
  const placedLabels = useRef<Array<[number, number, number, number]>>([]);
  const didFit = useRef(false);

  useEffect(() => {
    setTokens(readCanvasTokens());
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      setSize({ width: el.clientWidth, height: el.clientHeight });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const graphData = useMemo(() => {
    const subsetIds = new Set(
      graph.edges.filter((e) => e.subset).map((e) => e.source),
    );
    // Higher track counts first: they paint first and win label collisions.
    const nodes: MapNode[] = [...graph.nodes]
      .sort((a, b) => b.track_count - a.track_count)
      .map((n) => {
        const color = n.centroid ? acousticColor(n.centroid) : GREY_NODE;
        return {
          id: n.id,
          name: n.name,
          trackCount: n.track_count,
          fill: oklchString(color),
          ring: oklchString(selectionRing(color)),
          grey: n.centroid === null,
          isSubset: subsetIds.has(n.id),
        };
      });
    const links: MapLink[] = graph.edges.map((e) => ({
      source: e.source,
      target: e.target,
      shared: e.shared,
      subset: e.subset,
    }));
    return { nodes, links };
  }, [graph]);

  // The graph mounts only once tokens and container size exist — effects
  // that reach through fgRef must key off this, not run at first render.
  const graphMounted = tokens !== null && size.width > 0;

  // Layout spread: stronger repulsion and overlap-weighted link distances so
  // the constellation occupies real graph space — the fitted zoom then lands
  // near 1, where the spec's node radii and 12px labels are calibrated.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !graphMounted) return;
    const charge = fg.d3Force("charge") as
      | { strength?: (s: number) => void }
      | undefined;
    charge?.strength?.(-160);
    const link = fg.d3Force("link") as
      | { distance?: (fn: (l: MapLink) => number) => void }
      | undefined;
    link?.distance?.((l: MapLink) =>
      // Heavier overlap pulls playlists closer; subsets satellite tight.
      l.subset ? 55 : 150 - 90 * Math.min(1, l.shared / 40),
    );
    // Pairwise separation so discs (and their satellite rings) never overlap.
    // O(n²) per tick is nothing at library scale (~60 playlists).
    const collide = () => {
      const nodes = graphData.nodes;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          if (
            a.x === undefined ||
            a.y === undefined ||
            b.x === undefined ||
            b.y === undefined
          )
            continue;
          const minDist =
            nodeRadius(a.trackCount) + nodeRadius(b.trackCount) + 8;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          if (dist >= minDist) continue;
          const push = ((minDist - dist) / dist) * 0.5;
          a.vx = (a.vx ?? 0) - dx * push * 0.2;
          a.vy = (a.vy ?? 0) - dy * push * 0.2;
          b.vx = (b.vx ?? 0) + dx * push * 0.2;
          b.vy = (b.vy ?? 0) + dy * push * 0.2;
        }
      }
    };
    fg.d3Force("collide", collide);
    fg.d3ReheatSimulation();
  }, [graphMounted, graphData]);

  // Initial camera fit once the reheated layout has spread, with the zoom
  // capped so the framing approximates "median label legible at working
  // zoom" without ballooning node sizes.
  useEffect(() => {
    if (didFit.current || !graphMounted) return;
    const timer = setTimeout(() => {
      const fg = fgRef.current;
      if (!fg) return;
      fg.zoomToFit(0, 100);
      if (fg.zoom() > 1.3) fg.zoom(1.3, 0);
      didFit.current = true;
    }, 1100);
    return () => clearTimeout(timer);
  }, [graphMounted]);

  // Ambient breath (graph spec §7): the simulation never fully freezes. A
  // custom force adds sub-pixel velocity jitter each tick — a tide you sense
  // rather than see — while high velocity decay keeps aimed-at nodes still.
  // Reduced motion: no force, default cooldown, the map is a still chart.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !graphMounted) return;
    if (reducedMotion) {
      fg.d3Force("breath", null);
      return;
    }
    const breath = () => {
      for (const node of graphData.nodes) {
        node.vx = (node.vx ?? 0) + (Math.random() - 0.5) * 0.03;
        node.vy = (node.vy ?? 0) + (Math.random() - 0.5) * 0.03;
      }
    };
    fg.d3Force("breath", breath);
    return () => {
      fgRef.current?.d3Force("breath", null);
    };
  }, [reducedMotion, graphData, graphMounted]);

  // Right dock opening/closing: shift the camera so nodes never hide behind
  // the panel (docked-panel rule 5).
  const prevInset = useRef(0);
  useEffect(() => {
    const fg = fgRef.current;
    const delta = rightInset - prevInset.current;
    prevInset.current = rightInset;
    if (!fg || delta === 0) return;
    const center = fg.centerAt();
    const zoom = fg.zoom();
    if (center && zoom) {
      fg.centerAt(
        center.x + delta / (2 * zoom),
        center.y,
        reducedMotion ? 0 : 300,
      );
    }
  }, [rightInset, reducedMotion]);

  const isIncident = useCallback(
    (link: MapLink, id: number | null): boolean => {
      if (id === null) return false;
      const src =
        typeof link.source === "object" ? link.source.id : link.source;
      const tgt =
        typeof link.target === "object" ? link.target.id : link.target;
      return src === id || tgt === id;
    },
    [],
  );

  // Plain functions, not useCallback: the painter runs per frame off the
  // latest render's closure, so memoized identity buys nothing here.
  function paintNode(
    node: MapNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    const r = nodeRadius(node.trackCount);
    const hovered = node.id === hoveredId;
    const selected = node.id === selectedId;

    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = node.fill;
    ctx.fill();

    if (hovered && !selected) {
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = tokens.textPrimary;
      ctx.stroke();
    }

    if (selected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 1, 0, 2 * Math.PI);
      ctx.lineWidth = 2;
      ctx.strokeStyle = node.ring;
      ctx.stroke();
    }

    // Satellite ring: subset membership stays legible without color.
    if (node.isSubset) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
      ctx.lineWidth = 1;
      ctx.strokeStyle = tokens.borderStrong;
      ctx.stroke();
    }

    paintLabel(node, ctx, globalScale, r, hovered, selected);
  }

  function paintLabel(
    node: MapNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
    r: number,
    hovered: boolean,
    selected: boolean,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    const now = performance.now();
    const dt = Math.min(now - lastFrameAt.current, 100);

    const wanted = r * globalScale >= LABEL_THRESHOLD_PX || selected || hovered;
    const prev = labelAlpha.current.get(node.id) ?? 0;
    const step = reducedMotion ? 1 : dt / LABEL_FADE_MS;
    const alpha = Math.max(0, Math.min(1, prev + (wanted ? step : -step)));
    labelAlpha.current.set(node.id, alpha);
    if (alpha <= 0.01) return;

    const fontSize = 12;
    ctx.font = `${selected ? 700 : 400} ${fontSize}px ${tokens.fontText}`;
    const width = ctx.measureText(node.name).width;
    let lx = node.x + r + 8;
    // Flip the label to the left near the viewport's right edge.
    const screen = fgRef.current?.graph2ScreenCoords(lx + width, node.y);
    if (screen && screen.x > size.width - rightInset - 60) {
      lx = node.x - r - 8 - width;
    }
    const box: [number, number, number, number] = [
      lx,
      node.y - fontSize / 2,
      width,
      fontSize,
    ];

    // Collision: earlier (higher-track-count) labels win; selected/hovered
    // always render.
    if (!selected && !hovered) {
      for (const [px, py, pw, ph] of placedLabels.current) {
        if (
          box[0] < px + pw &&
          box[0] + box[2] > px &&
          box[1] < py + ph &&
          box[1] + box[3] > py
        ) {
          return;
        }
      }
    }
    placedLabels.current.push(box);

    ctx.globalAlpha = alpha;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillStyle =
      hovered || selected
        ? tokens.textPrimary
        : node.grey
          ? tokens.textMuted
          : tokens.textSecondary;
    ctx.fillText(node.name, lx, node.y);
    ctx.globalAlpha = 1;
  }

  const paintPointerArea = useCallback(
    (node: MapNode, color: string, ctx: CanvasRenderingContext2D) => {
      if (node.x === undefined || node.y === undefined) return;
      ctx.beginPath();
      ctx.arc(node.x, node.y, nodeRadius(node.trackCount) + 3, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    },
    [],
  );

  const handleHover = useCallback((node: MapNode | null) => {
    setHoveredId(node ? node.id : null);
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    if (!node) {
      setHoverCard(null);
      return;
    }
    // Hover card appears after a 220ms dwell (graph spec §1).
    hoverTimer.current = setTimeout(() => {
      const fg = fgRef.current;
      if (!fg || node.x === undefined || node.y === undefined) return;
      const screen = fg.graph2ScreenCoords(node.x, node.y);
      setHoverCard({ nodeId: node.id, x: screen.x, y: screen.y });
    }, HOVER_CARD_DELAY_MS);
  }, []);

  const hoveredNode = hoverCard
    ? (graph.nodes.find((n) => n.id === hoverCard.nodeId) ?? null)
    : null;

  return (
    <div ref={containerRef} className="absolute inset-0">
      {tokens && size.width > 0 && (
        <ForceGraph2D
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          nodeCanvasObject={paintNode}
          nodePointerAreaPaint={paintPointerArea}
          nodeLabel={() => ""}
          onNodeHover={handleHover}
          onNodeClick={(node) => onSelect(node.id)}
          onNodeRightClick={(node, event) => {
            event.preventDefault();
            onNodeContextMenu?.(node.id, event.clientX, event.clientY);
          }}
          onBackgroundClick={() => onSelect(null)}
          onRenderFramePre={() => {
            placedLabels.current = [];
          }}
          onRenderFramePost={() => {
            lastFrameAt.current = performance.now();
          }}
          linkWidth={(link) => (link.subset ? 1.25 : edgeWidth(link.shared))}
          linkLineDash={(link) => (link.subset ? [3, 2] : null)}
          linkColor={(link) =>
            isIncident(link, hoveredId) || isIncident(link, selectedId)
              ? tokens.borderStrong
              : tokens.borderSubtle
          }
          linkVisibility={(link) =>
            link.shared >= 3 ||
            link.subset ||
            isIncident(link, hoveredId) ||
            isIncident(link, selectedId)
          }
          // Engine stays alive so the breath force keeps ticking; under
          // reduced motion the default cooldown lets the layout settle fully.
          // Warmup pre-runs the layout so the first paint is already spread
          // out and the initial fit frames the real constellation.
          warmupTicks={150}
          d3VelocityDecay={0.55}
          cooldownTime={reducedMotion ? 15_000 : Infinity}
        />
      )}
      {hoveredNode && hoverCard && (
        <GraphHoverCard
          node={hoveredNode}
          edges={graph.edges}
          nodes={graph.nodes}
          x={hoverCard.x}
          y={hoverCard.y}
          containerWidth={size.width}
        />
      )}
    </div>
  );
}
