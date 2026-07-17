"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import { ArtistHoverCard } from "@/components/canvas/rich-hover-card";
import type {
  GalaxyEdge,
  GalaxyNode as GalaxyNodeData,
} from "@/lib/api/schemas";
import type { FlyTarget } from "@/lib/canvas/fly-to";
import { shouldFireFlyTo } from "@/lib/canvas/fly-to";
import { artistCardModel } from "@/lib/canvas/hover-card";
import { useBreathDrift } from "@/lib/canvas/use-breath-drift";
import { useCanvasWheel } from "@/lib/canvas/use-canvas-wheel";
import { parseOklch } from "@/lib/color/acoustic";
import {
  type GalaxyEdgeKind,
  galaxyEdgeDash,
  galaxyEdgeWidth,
} from "@/lib/galaxy/logic";
import { type CanvasTokens, readCanvasTokens } from "@/lib/graph/canvas-tokens";
import { nodeRadius } from "@/lib/graph/geometry";

/** One artist, render-ready: colors resolved, sizing input carried. */
export interface GalaxyRenderNode {
  id: string;
  name: string;
  trackCount: number;
  /** Resolved oklch() fill — acoustic mapping of the artist's track centroid. */
  fill: string;
  /** Selection-ring color: own color at L+0.12, chroma re-clamped. */
  ring: string;
  grey: boolean;
}

interface GalaxyLinkData {
  kind: GalaxyEdgeKind;
  weight: number;
}

type GalaxyNode = NodeObject<GalaxyRenderNode>;
type GalaxyLink = LinkObject<GalaxyRenderNode, GalaxyLinkData>;

const LABEL_THRESHOLD_PX = 8;
const LABEL_FADE_MS = 150;
const HOVER_CARD_DELAY_MS = 260;
const FLY_TO_MS = 650;

interface PlacedLabel {
  id: string;
  x: number;
  y: number;
  text: string;
  color: string;
  weight: number;
  box: [number, number, number, number];
}

interface ArtistGalaxyCanvasProps {
  nodes: GalaxyRenderNode[];
  edges: GalaxyEdge[];
  /** Full artist payloads by id — the hover card reads photo/genres/similar. */
  nodeData: Map<string, GalaxyNodeData>;
  /** Artist keys kept at full strength (bridge highlight). Null = no veil. */
  highlightIds: Set<string> | null;
  selectedId: string | null;
  onSelect: (artistId: string | null) => void;
  rightInset: number;
  reducedMotion: boolean;
  /** Camera fly-to target for the galaxy (search-to-focus). */
  flyTo?: FlyTarget | null;
}

/**
 * The artist galaxy: force layout in the playlist graph's visual language
 * (graph rendering spec §10). Co-playlist edges are solid, weight = shared
 * playlists; similarity edges are dashed 3-2 — relation kind lives in line
 * style, never hue. Bridge highlighting repaints member artists over a
 * draw-time veil, the same technique as the deck dim and the field legend.
 */
export default function ArtistGalaxyCanvas({
  nodes,
  edges,
  nodeData,
  highlightIds,
  selectedId,
  onSelect,
  rightInset,
  reducedMotion,
  flyTo = null,
}: ArtistGalaxyCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods<GalaxyNode, GalaxyLink> | undefined>(
    undefined,
  );
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [tokens, setTokens] = useState<CanvasTokens | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [hoverCard, setHoverCard] = useState<{
    artistId: string;
    x: number;
    y: number;
  } | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gesturingUntil = useRef(0);

  const nodeById = useMemo(() => {
    const m = new Map<string, GalaxyNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  const labelAlpha = useRef(new Map<string, number>());
  const lastFrameAt = useRef(0);
  const placedLabels = useRef<PlacedLabel[]>([]);
  const didFit = useRef(false);

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

  const graphData = useMemo(() => {
    // Higher track counts paint first and win label collisions.
    const sorted = [...nodes].sort((a, b) => b.trackCount - a.trackCount);
    const ids = new Set(sorted.map((n) => n.id));
    const links: GalaxyLink[] = edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        kind: e.kind,
        weight: e.weight,
      }));
    return { nodes: sorted.map((n): GalaxyNode => ({ ...n })), links };
  }, [nodes, edges]);

  const graphMounted = tokens !== null && size.width > 0;

  // Layout: co-playlist weight pulls artists together; similarity edges tie
  // tighter still (they assert the artists sound alike). Charge is softer
  // than the playlist graph's — more nodes, smaller discs.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !graphMounted) return;
    const charge = fg.d3Force("charge") as
      | { strength?: (s: number) => void }
      | undefined;
    charge?.strength?.(-90);
    const link = fg.d3Force("link") as
      | { distance?: (fn: (l: GalaxyLink) => number) => void }
      | undefined;
    link?.distance?.((l: GalaxyLink) =>
      l.kind === "similarity" ? 60 : 140 - 80 * Math.min(1, l.weight / 6),
    );
    // Pairwise separation keeps discs hittable. O(n²) per tick is fine at
    // the payload's 300-node cap.
    const collide = () => {
      const list = graphData.nodes;
      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          const a = list[i];
          const b = list[j];
          if (
            a.x === undefined ||
            a.y === undefined ||
            b.x === undefined ||
            b.y === undefined
          )
            continue;
          const minDist =
            nodeRadius(a.trackCount) + nodeRadius(b.trackCount) + 6;
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

  // Initial camera fit once the layout spreads.
  useEffect(() => {
    if (didFit.current || !graphMounted) return;
    const timer = setTimeout(() => {
      const fg = fgRef.current;
      if (!fg) return;
      fg.zoomToFit(0, 80);
      if (fg.zoom() > 1.3) fg.zoom(1.3, 0);
      didFit.current = true;
    }, 1100);
    return () => clearTimeout(timer);
  }, [graphMounted]);

  // Fly-to (search-to-focus): glide to the searched artist, once per nonce.
  const lastFlyNonce = useRef(0);
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !shouldFireFlyTo(flyTo, lastFlyNonce.current)) return;
    lastFlyNonce.current = flyTo?.nonce ?? 0;
    const target = graphData.nodes.find((n) => n.id === flyTo?.id);
    if (!target || target.x === undefined || target.y === undefined) return;
    const duration = reducedMotion ? 0 : FLY_TO_MS;
    fg.centerAt(target.x, target.y, duration);
    if (fg.zoom() < 1.5) fg.zoom(1.5, duration);
    if (typeof flyTo?.id === "string") onSelect(flyTo.id);
  }, [flyTo, graphData, reducedMotion, onSelect]);

  // Ambient breath (graph spec §7): once the layout settles, an own RAF loop
  // pins each node to `rest + deterministic sine drift`, keeping the galaxy
  // gently in motion for the whole session — independent of d3's alpha
  // lifecycle. A velocity-jitter force nets to sub-pixel once the simulation
  // cools and dies for good after a burst of pan/zoom; pinning fx/fy (applied
  // verbatim by d3 each tick) is immune to settle, reheats, and interaction.
  // Reduced motion: loop never runs, the galaxy is a still chart.
  const setDragging = useBreathDrift(
    graphData.nodes,
    !reducedMotion && graphMounted,
  );

  // Right dock opening/closing shifts the camera (docked-panel rule 5).
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
    (link: GalaxyLink, id: string | null): boolean => {
      if (id === null) return false;
      const src =
        typeof link.source === "object" ? link.source.id : link.source;
      const tgt =
        typeof link.target === "object" ? link.target.id : link.target;
      return src === id || tgt === id;
    },
    [],
  );

  function drawDisc(
    ctx: CanvasRenderingContext2D,
    node: GalaxyNode,
    hovered: boolean,
    selected: boolean,
    tk: CanvasTokens,
  ) {
    if (node.x === undefined || node.y === undefined) return;
    const r = nodeRadius(node.trackCount);
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = node.fill;
    ctx.fill();
    if (hovered && !selected) {
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = tk.textPrimary;
      ctx.stroke();
    }
    if (selected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 1, 0, 2 * Math.PI);
      ctx.lineWidth = 2;
      ctx.strokeStyle = node.ring;
      ctx.stroke();
    }
  }

  function paintNode(
    node: GalaxyNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    const hovered = node.id === hoveredId;
    const selected = node.id === selectedId;
    drawDisc(ctx, node, hovered, selected, tokens);
    paintLabel(node, ctx, globalScale, hovered, selected);
  }

  function paintLabel(
    node: GalaxyNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
    hovered: boolean,
    selected: boolean,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    const r = nodeRadius(node.trackCount);
    const now = performance.now();
    const dt = Math.min(now - lastFrameAt.current, 100);

    const wanted = r * globalScale >= LABEL_THRESHOLD_PX || selected || hovered;
    const prev = labelAlpha.current.get(node.id) ?? 0;
    const step = reducedMotion ? 1 : dt / LABEL_FADE_MS;
    const alpha = Math.max(0, Math.min(1, prev + (wanted ? step : -step)));
    labelAlpha.current.set(node.id, alpha);
    if (alpha <= 0.01) return;

    const fontSize = 12;
    const weight = selected ? 700 : 400;
    ctx.font = `${weight} ${fontSize}px ${tokens.fontText}`;
    const width = ctx.measureText(node.name).width;
    let lx = node.x + r + 8;
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

    if (!selected && !hovered) {
      for (const placed of placedLabels.current) {
        const [px, py, pw, ph] = placed.box;
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

    const color =
      hovered || selected
        ? tokens.textPrimary
        : node.grey
          ? tokens.textMuted
          : tokens.textSecondary;
    placedLabels.current.push({
      id: node.id,
      x: lx,
      y: node.y,
      text: node.name,
      color,
      weight,
      box,
    });

    ctx.globalAlpha = alpha;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillStyle = color;
    ctx.fillText(node.name, lx, node.y);
    ctx.globalAlpha = 1;
  }

  /**
   * Bridge highlight: canvas-color veil over the frame, then the bridging
   * artists (plus hover/selection) repainted at full strength on top —
   * draw-time dimming, never a DOM scrim.
   */
  function paintHighlight(ctx: CanvasRenderingContext2D) {
    if (!highlightIds || !tokens) return;
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

    for (const node of graphData.nodes) {
      const keep =
        highlightIds.has(node.id) ||
        node.id === hoveredId ||
        node.id === selectedId;
      if (!keep) continue;
      drawDisc(
        ctx,
        node,
        node.id === hoveredId,
        node.id === selectedId,
        tokens,
      );
    }
    for (const placed of placedLabels.current) {
      const keep =
        highlightIds.has(placed.id) ||
        placed.id === hoveredId ||
        placed.id === selectedId;
      if (!keep) continue;
      ctx.font = `${placed.weight} 12px ${tokens.fontText}`;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      ctx.fillStyle = placed.color;
      ctx.fillText(placed.text, placed.x, placed.y);
    }
  }

  const paintPointerArea = useCallback(
    (node: GalaxyNode, color: string, ctx: CanvasRenderingContext2D) => {
      if (node.x === undefined || node.y === undefined) return;
      ctx.beginPath();
      ctx.arc(node.x, node.y, nodeRadius(node.trackCount) + 3, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    },
    [],
  );

  // Artist hover card on dwell (photo + genres + similar). Hidden while
  // panning/zooming so it never chases the cursor mid-gesture.
  const handleHover = useCallback((node: GalaxyNode | null) => {
    setHoveredId(node ? node.id : null);
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    if (!node) {
      setHoverCard(null);
      return;
    }
    hoverTimer.current = setTimeout(() => {
      const fg = fgRef.current;
      if (!fg || node.x === undefined || node.y === undefined) return;
      if (performance.now() < gesturingUntil.current) return;
      const screen = fg.graph2ScreenCoords(node.x, node.y);
      setHoverCard({ artistId: node.id, x: screen.x, y: screen.y });
    }, HOVER_CARD_DELAY_MS);
  }, []);

  const hoveredData = hoverCard ? nodeData.get(hoverCard.artistId) : null;
  const hoveredRender = hoverCard ? nodeById.get(hoverCard.artistId) : null;

  return (
    <div ref={containerRef} className="absolute inset-0">
      {graphMounted && (
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
          onZoom={() => {
            gesturingUntil.current = performance.now() + 220;
            setHoverCard(null);
          }}
          // Suspend ambient drift on the dragged node so the RAF pin does not
          // fight the drag; the library owns its fx/fy until release.
          onNodeDrag={(node) => setDragging(node.id)}
          onNodeDragEnd={() => setDragging(null)}
          onBackgroundClick={() => onSelect(null)}
          onRenderFramePre={() => {
            placedLabels.current = [];
          }}
          onRenderFramePost={(ctx) => {
            paintHighlight(ctx);
            lastFrameAt.current = performance.now();
          }}
          linkWidth={(link) => galaxyEdgeWidth(link.kind, link.weight)}
          linkLineDash={(link) => galaxyEdgeDash(link.kind)}
          linkColor={(link) =>
            isIncident(link, hoveredId) || isIncident(link, selectedId)
              ? tokens.borderStrong
              : tokens.borderSubtle
          }
          // Weight-1 co-playlist edges render only around the artist in
          // hand — density without noise. Similarity edges always show.
          linkVisibility={(link) =>
            link.kind === "similarity" ||
            link.weight >= 2 ||
            isIncident(link, hoveredId) ||
            isIncident(link, selectedId)
          }
          // cooldownTime=Infinity keeps the library's redraw loop alive so the
          // canvas repaints the drift positions the breath RAF loop writes.
          enableZoomInteraction={false}
          warmupTicks={150}
          d3VelocityDecay={0.55}
          cooldownTime={reducedMotion ? 15_000 : Infinity}
        />
      )}
      {hoverCard && hoveredData && hoveredRender && (
        <ArtistHoverCard
          model={artistCardModel(hoveredData)}
          color={parseOklch(hoveredRender.fill)}
          x={hoverCard.x}
          y={hoverCard.y}
          containerWidth={size.width}
          containerHeight={size.height}
          rightInset={rightInset}
        />
      )}
    </div>
  );
}
