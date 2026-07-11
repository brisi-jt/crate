"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import { type ClusterHull, POINT_RADIUS } from "@/lib/field/layout";
import { type CanvasTokens, readCanvasTokens } from "@/lib/graph/canvas-tokens";

/** One projected track, position pinned — the field never simulates. */
export interface FieldRenderPoint {
  id: number;
  name: string;
  artist: string;
  cluster: number;
  x: number;
  y: number;
  /** Resolved oklch() fill — acoustic mapping via features or owners. */
  fill: string;
  /** Selection-ring color: own color at L+0.12, chroma re-clamped. */
  ring: string;
  grey: boolean;
}

type FieldNode = NodeObject<FieldRenderPoint>;
type FieldLink = LinkObject<FieldRenderPoint, Record<string, never>>;

const LABEL_THRESHOLD_PX = 8;
const LABEL_FADE_MS = 150;
const HULL_PAD = 26;

interface PlacedLabel {
  id: number;
  x: number;
  y: number;
  text: string;
  color: string;
  weight: number;
  box: [number, number, number, number];
}

interface TrackFieldCanvasProps {
  points: FieldRenderPoint[];
  /** Cluster hull outlines; null = overlay off. */
  hulls: ClusterHull[] | null;
  /** Track ids kept at full strength; everything else recedes. Null = no highlight. */
  highlightIds: Set<number> | null;
  selectedId: number | null;
  onSelect: (trackId: number | null) => void;
  rightInset: number;
  reducedMotion: boolean;
}

/**
 * The track field: UMAP positions rendered as a still scatter — stable
 * coordinates, no force simulation, same visual language as the playlist
 * graph (graph rendering spec §10) at a constant 3px point radius.
 */
export default function TrackFieldCanvas({
  points,
  hulls,
  highlightIds,
  selectedId,
  onSelect,
  rightInset,
  reducedMotion,
}: TrackFieldCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods<FieldNode, FieldLink> | undefined>(
    undefined,
  );
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [tokens, setTokens] = useState<CanvasTokens | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);

  const labelAlpha = useRef(new Map<number, number>());
  const lastFrameAt = useRef(0);
  const placedLabels = useRef<PlacedLabel[]>([]);
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

  // Positions are data, not simulation output: every point is pinned. The
  // parent memoizes `points`, so this only rebuilds when the field changes
  // (scope flip, membership pages landing, payload refresh).
  const graphData = useMemo(
    () => ({
      nodes: points.map((p): FieldNode => ({ ...p, fx: p.x, fy: p.y })),
      links: [] as FieldLink[],
    }),
    [points],
  );

  const graphMounted = tokens !== null && size.width > 0;

  // One initial fit: the whole field framed, gently inset.
  useEffect(() => {
    if (didFit.current || !graphMounted || points.length === 0) return;
    const timer = setTimeout(() => {
      const fg = fgRef.current;
      if (!fg) return;
      fg.zoomToFit(0, 60);
      if (fg.zoom() > 2) fg.zoom(2, 0);
      didFit.current = true;
    }, 60);
    return () => clearTimeout(timer);
  }, [graphMounted, points.length]);

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

  function paintHulls(ctx: CanvasRenderingContext2D) {
    if (!hulls || !tokens) return;
    ctx.save();
    for (const { cluster, hull } of hulls) {
      if (hull.length === 0) continue;
      ctx.beginPath();
      ctx.moveTo(hull[0].x, hull[0].y);
      for (let i = 1; i < hull.length; i++) ctx.lineTo(hull[i].x, hull[i].y);
      ctx.closePath();
      // Soft halo: a wide round-joined stroke in the panel surface color
      // pads the hull outward with rounded corners — structure, not sound,
      // so the tint is neutral (one lightness step above the canvas).
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.lineWidth = HULL_PAD;
      ctx.strokeStyle = tokens.surface1;
      ctx.fillStyle = tokens.surface1;
      ctx.stroke();
      ctx.fill();

      // Cluster id, micro caps — cross-reference for the stats panel's
      // split/merge readouts.
      let cx = 0;
      let cy = 0;
      for (const p of hull) {
        cx += p.x;
        cy += p.y;
      }
      ctx.font = `400 14px ${tokens.fontData}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = tokens.textMuted;
      ctx.fillText(`C${cluster}`, cx / hull.length, cy / hull.length);
    }
    ctx.restore();
  }

  function paintPoint(
    node: FieldNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    const hovered = node.id === hoveredId;
    const selected = node.id === selectedId;

    drawDisc(ctx, node, hovered, selected, tokens);
    paintLabel(node, ctx, globalScale, hovered, selected);
  }

  function drawDisc(
    ctx: CanvasRenderingContext2D,
    node: FieldNode,
    hovered: boolean,
    selected: boolean,
    tk: CanvasTokens,
  ) {
    if (node.x === undefined || node.y === undefined) return;
    ctx.beginPath();
    ctx.arc(node.x, node.y, POINT_RADIUS, 0, 2 * Math.PI);
    ctx.fillStyle = node.fill;
    ctx.fill();
    if (hovered && !selected) {
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = tk.textPrimary;
      ctx.stroke();
    }
    if (selected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, POINT_RADIUS + 2, 0, 2 * Math.PI);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = node.ring;
      ctx.stroke();
    }
  }

  function paintLabel(
    node: FieldNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
    hovered: boolean,
    selected: boolean,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    const now = performance.now();
    const dt = Math.min(now - lastFrameAt.current, 100);

    // Deep-zoom threshold: a 3px point crosses 8 screen px near zoom 2.7.
    const wanted =
      POINT_RADIUS * globalScale >= LABEL_THRESHOLD_PX || selected || hovered;
    const prev = labelAlpha.current.get(node.id) ?? 0;
    const step = reducedMotion ? 1 : dt / LABEL_FADE_MS;
    const alpha = Math.max(0, Math.min(1, prev + (wanted ? step : -step)));
    labelAlpha.current.set(node.id, alpha);
    if (alpha <= 0.01) return;

    const text =
      hovered || selected ? `${node.name} — ${node.artist}` : node.name;
    const fontSize = 12;
    const weight = selected ? 700 : 400;
    ctx.font = `${weight} ${fontSize}px ${tokens.fontText}`;
    const width = ctx.measureText(text).width;
    let lx = node.x + POINT_RADIUS + 6;
    const screen = fgRef.current?.graph2ScreenCoords(lx + width, node.y);
    if (screen && screen.x > size.width - rightInset - 60) {
      lx = node.x - POINT_RADIUS - 6 - width;
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
      text,
      color,
      weight,
      box,
    });

    ctx.globalAlpha = alpha;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillStyle = color;
    ctx.fillText(text, lx, node.y);
    ctx.globalAlpha = 1;
  }

  /**
   * Playlist highlight (legend hover/pin or selected playlist): a
   * canvas-color veil over the frame, then the member points repainted at
   * full strength — draw-time dimming, mirroring the deck's dim state.
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
    // Labels that made it through collision get restored for kept points.
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
    (node: FieldNode, color: string, ctx: CanvasRenderingContext2D) => {
      if (node.x === undefined || node.y === undefined) return;
      ctx.beginPath();
      ctx.arc(node.x, node.y, POINT_RADIUS + 4, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    },
    [],
  );

  return (
    <div ref={containerRef} className="absolute inset-0">
      {graphMounted && (
        <ForceGraph2D
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          nodeCanvasObject={paintPoint}
          nodePointerAreaPaint={paintPointerArea}
          nodeLabel={() => ""}
          enableNodeDrag={false}
          onNodeHover={(node) => setHoveredId(node ? node.id : null)}
          onNodeClick={(node) => onSelect(node.id)}
          onBackgroundClick={() => onSelect(null)}
          onRenderFramePre={(ctx) => {
            placedLabels.current = [];
            paintHulls(ctx);
          }}
          onRenderFramePost={(ctx) => {
            paintHighlight(ctx);
            lastFrameAt.current = performance.now();
          }}
          // No simulation: positions are UMAP output, pinned. Zero ticks —
          // the field is a still chart that only the camera moves.
          warmupTicks={0}
          cooldownTicks={0}
        />
      )}
    </div>
  );
}
