"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import type { GraphResponse } from "@/lib/api/schemas";
import { useBreathDrift } from "@/lib/canvas/use-breath-drift";
import { useCanvasWheel } from "@/lib/canvas/use-canvas-wheel";
import { GREY_NODE, oklchString, selectionRing } from "@/lib/color/acoustic";
import { equalizedColor, rankEqualize } from "@/lib/color/equalize";
import { type CanvasTokens, readCanvasTokens } from "@/lib/graph/canvas-tokens";
import { edgeWidth, nodeRadius } from "@/lib/graph/geometry";
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

// Radius/width formulas live in lib/graph/geometry so non-canvas modules
// (deck ghost placement) share them without importing the force-graph lib.

const LABEL_THRESHOLD_PX = 8;
const LABEL_FADE_MS = 150;
const HOVER_CARD_DELAY_MS = 220;

/** The auditioning candidate, rendered as a ghost near its target playlist. */
export interface GhostRender {
  title: string;
  /** Candidate acoustic color (dashed stroke + pulse halo). */
  stroke: string;
  /** Solid fill, pre-mixed 25% toward the canvas. */
  fill: string;
  /** Graph-space offset from the target node's center. */
  offset: { dx: number; dy: number };
  playing: boolean;
}

/** Dimmed-map state while the listening deck is open. */
export interface DimState {
  targetId: number;
  ghost: GhostRender | null;
}

/** Camera move request; bump nonce to re-fire for the same node. */
export interface FlyToRequest {
  nodeId: number;
  nonce: number;
}

const FLY_TO_MS = 650;
const GHOST_RADIUS = 7;
const PULSE_PERIOD_MS = 2800;

interface GraphCanvasProps {
  graph: GraphResponse;
  selectedId: number | null;
  onSelect: (playlistId: number | null) => void;
  /** Right-click on a node — opens the map context menu at screen coords. */
  onNodeContextMenu?: (playlistId: number, x: number, y: number) => void;
  /** Right-dock width in px — fit and camera moves respect the inset. */
  rightInset: number;
  reducedMotion: boolean;
  /** Deck-open dimming: everything but the target and ghost recedes. */
  dim?: DimState | null;
  /** Fly the camera to a node (transport artwork click). */
  flyTo?: FlyToRequest | null;
}

export default function GraphCanvas({
  graph,
  selectedId,
  onSelect,
  onNodeContextMenu,
  rightInset,
  reducedMotion,
  dim = null,
  flyTo = null,
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

  // Two-finger pan / pinch-zoom: intercept wheel events before the library
  // sees them. enableZoomInteraction={false} disables the default scroll-to-
  // zoom so this handler is the sole wheel consumer.
  useCanvasWheel(containerRef, fgRef);

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

  // G4 — rank-equalize the palette across the library so playlist colours fill
  // the gamut instead of piling on red (centroids regress to the mean hardest
  // of all — measured p10–p90 acousticness 0.21–0.59). Shared by the painter
  // and the hover-card swatch so they always agree.
  const equalizer = useMemo(() => {
    const centroids = graph.nodes
      .map((n) => n.centroid)
      .filter((c): c is NonNullable<typeof c> => c !== null);
    return centroids.length > 0 ? rankEqualize(centroids) : null;
  }, [graph.nodes]);

  const graphData = useMemo(() => {
    const subsetIds = new Set(
      graph.edges.filter((e) => e.subset).map((e) => e.source),
    );
    const eq = equalizer;
    // Higher track counts first: they paint first and win label collisions.
    const nodes: MapNode[] = [...graph.nodes]
      .sort((a, b) => b.track_count - a.track_count)
      .map((n) => {
        const color = n.centroid
          ? eq
            ? equalizedColor(n.centroid, eq)
            : GREY_NODE
          : GREY_NODE;
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
  }, [graph, equalizer]);

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

  // Ambient breath (graph spec §7): once the layout settles, an own RAF loop
  // pins each node to `rest + deterministic sine drift`, so the constellation
  // keeps drifting — visible at a glance, calm while reading — for the whole
  // session. This is deliberately independent of d3's alpha lifecycle: a
  // velocity-jitter force nets to sub-pixel once the simulation cools, and a
  // burst of panning/zooming drives the layout into a minimum that reheats
  // cannot revive, so the graph froze after the first interaction. Pinning
  // fx/fy (which d3 applies verbatim each tick) makes the drift immune to
  // settle, reheats, and every pan/zoom/drag. Reduced motion: loop never runs.
  const setDragging = useBreathDrift(
    graphData.nodes,
    !reducedMotion && graphMounted,
  );

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

  // Fly-to (transport artwork click / deck open): 650ms glide, capped zoom.
  const lastFlyNonce = useRef(0);
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !flyTo || flyTo.nonce === lastFlyNonce.current) return;
    lastFlyNonce.current = flyTo.nonce;
    const node = graphData.nodes.find((n) => n.id === flyTo.nodeId);
    if (!node || node.x === undefined || node.y === undefined) return;
    const duration = reducedMotion ? 0 : FLY_TO_MS;
    // While the deck occupies the bottom-center, land the target in the
    // upper map area instead of behind the deck card.
    const yOffset = dim ? 140 / Math.max(fg.zoom(), 0.1) : 0;
    fg.centerAt(node.x, node.y + yOffset, duration);
    if (fg.zoom() < 1.0) fg.zoom(1.0, duration);
  }, [flyTo, graphData, reducedMotion, dim]);

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
    // Dimmed map: labels vanish except the target's (repainted post-frame).
    if (dim && node.id !== dim.targetId) return;
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

  /**
   * Dimmed-map state (deck open): a canvas-color veil over the whole frame,
   * then the target playlist and the auditioning ghost repainted at full
   * strength on top — draw-time dimming, not a DOM scrim.
   */
  function paintDimOverlay(ctx: CanvasRenderingContext2D) {
    if (!dim || !tokens) return;
    const fg = fgRef.current;
    if (!fg) return;
    const topLeft = fg.screen2GraphCoords(0, 0);
    const bottomRight = fg.screen2GraphCoords(size.width, size.height);
    ctx.save();
    ctx.globalAlpha = 0.6;
    ctx.fillStyle = tokens.canvas;
    ctx.fillRect(
      topLeft.x,
      topLeft.y,
      bottomRight.x - topLeft.x,
      bottomRight.y - topLeft.y,
    );
    ctx.restore();

    const target = graphData.nodes.find((n) => n.id === dim.targetId);
    if (!target || target.x === undefined || target.y === undefined) return;
    const r = nodeRadius(target.trackCount);

    ctx.beginPath();
    ctx.arc(target.x, target.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = target.fill;
    ctx.fill();
    if (target.id === selectedId) {
      ctx.beginPath();
      ctx.arc(target.x, target.y, r + 1, 0, 2 * Math.PI);
      ctx.lineWidth = 2;
      ctx.strokeStyle = target.ring;
      ctx.stroke();
    }
    if (target.isSubset) {
      ctx.beginPath();
      ctx.arc(target.x, target.y, r + 3, 0, 2 * Math.PI);
      ctx.lineWidth = 1;
      ctx.strokeStyle = tokens.borderStrong;
      ctx.stroke();
    }
    ctx.font = `700 12px ${tokens.fontText}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillStyle = tokens.textPrimary;
    ctx.fillText(target.name, target.x + r + 8, target.y);

    const ghost = dim.ghost;
    if (!ghost) return;
    const gx = target.x + ghost.offset.dx;
    const gy = target.y + ghost.offset.dy;

    // Tether: dotted 1-3 hairline (provisional ≠ the subset dash).
    const angle = Math.atan2(target.y - gy, target.x - gx);
    ctx.save();
    ctx.setLineDash([1, 3]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = tokens.borderSubtle;
    ctx.beginPath();
    ctx.moveTo(
      gx + Math.cos(angle) * GHOST_RADIUS,
      gy + Math.sin(angle) * GHOST_RADIUS,
    );
    ctx.lineTo(target.x - Math.cos(angle) * r, target.y - Math.sin(angle) * r);
    ctx.stroke();
    ctx.restore();

    // Playing pulse (spec §4): 2.8s sine; static double-ring under reduced
    // motion. The halo exists only while auditioning — never decoration.
    let discScale = 1;
    if (ghost.playing) {
      let haloOffset = 8;
      let haloOpacity = 0.25;
      if (!reducedMotion) {
        const phase = (performance.now() % PULSE_PERIOD_MS) / PULSE_PERIOD_MS;
        const wave = 0.5 - 0.5 * Math.cos(2 * Math.PI * phase);
        haloOffset = 6 + 4 * wave;
        haloOpacity = 0.12 + 0.18 * wave;
        discScale = 1 + 0.045 * wave;
      }
      ctx.save();
      ctx.beginPath();
      ctx.arc(gx, gy, GHOST_RADIUS + haloOffset, 0, 2 * Math.PI);
      ctx.lineWidth = 2;
      ctx.strokeStyle = ghost.stroke;
      ctx.globalAlpha = haloOpacity;
      ctx.stroke();
      ctx.restore();
    }

    ctx.save();
    ctx.beginPath();
    ctx.arc(gx, gy, GHOST_RADIUS * discScale, 0, 2 * Math.PI);
    ctx.fillStyle = ghost.fill;
    ctx.fill();
    ctx.setLineDash([3, 2]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = ghost.stroke;
    ctx.stroke();
    ctx.restore();

    // Ghost label: always visible while the deck is open.
    ctx.font = `400 13px ${tokens.fontText}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";
    ctx.fillStyle = tokens.textSecondary;
    ctx.fillText(ghost.title, gx - GHOST_RADIUS - 8, gy);
    ctx.textAlign = "left";
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

  const handleHover = useCallback(
    (hoveredNode: MapNode | null) => {
      // While the deck dims the map, only the target playlist stays hoverable.
      const node =
        dim && hoveredNode && hoveredNode.id !== dim.targetId
          ? null
          : hoveredNode;
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
    },
    [dim],
  );

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
          onNodeClick={(node) => {
            // Guard against misfiles mid-audition: only the target reacts.
            if (dim && node.id !== dim.targetId) return;
            onSelect(node.id);
          }}
          onNodeRightClick={(node, event) => {
            if (dim && node.id !== dim.targetId) return;
            event.preventDefault();
            onNodeContextMenu?.(node.id, event.clientX, event.clientY);
          }}
          // Suspend ambient drift on the dragged node so the RAF pin does not
          // fight the drag; the library owns its fx/fy until release.
          onNodeDrag={(node) => setDragging(node.id)}
          onNodeDragEnd={() => setDragging(null)}
          onBackgroundClick={() => {
            if (dim) return;
            onSelect(null);
          }}
          onRenderFramePre={() => {
            placedLabels.current = [];
          }}
          onRenderFramePost={(ctx) => {
            paintDimOverlay(ctx);
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
          // cooldownTime=Infinity keeps the library's redraw loop running so the
          // canvas repaints the drift positions the breath RAF loop writes each
          // frame (autoPauseRedraw only paints while the engine is "running").
          // Under reduced motion the layout settles into a still chart.
          // Warmup pre-runs the layout so the first paint is already spread.
          enableZoomInteraction={false}
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
          equalizer={equalizer}
        />
      )}
    </div>
  );
}
