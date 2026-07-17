"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import { CanvasMinimap } from "@/components/canvas/canvas-minimap";
import { TrackHoverCard } from "@/components/canvas/rich-hover-card";
import type { FlyTarget } from "@/lib/canvas/fly-to";
import { shouldFireFlyTo } from "@/lib/canvas/fly-to";
import type { TrackCardModel } from "@/lib/canvas/hover-card";
import { fingerprintBars } from "@/lib/canvas/hover-card";
import { useCanvasWheel } from "@/lib/canvas/use-canvas-wheel";
import type { AcousticCentroid } from "@/lib/color/acoustic";
import { parseOklch } from "@/lib/color/acoustic";
import { type ClusterHull, POINT_RADIUS } from "@/lib/field/layout";
import { clusterBlobs, fieldLod } from "@/lib/field/lod";
import { type CanvasTokens, readCanvasTokens } from "@/lib/graph/canvas-tokens";

/** One projected track, position pinned — the field never simulates. */
export interface FieldRenderPoint {
  id: number;
  name: string;
  artist: string;
  cluster: number;
  x: number;
  y: number;
  /** Small album-art thumb url for the G1 hover card; null until imaged. */
  albumImageUrl: string | null;
  /** Per-track features for the hover-card fingerprint; null when unenriched. */
  features: AcousticCentroid | null;
  /** Owning-playlist count for the hover-card readout. */
  playlistCount: number;
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

const HOVER_CARD_DELAY_MS = 260;
const FLY_TO_MS = 650;

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
  /** G5 — camera fly-to target for the track field (search-to-focus). */
  flyTo?: FlyTarget | null;
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
  flyTo = null,
}: TrackFieldCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods<FieldNode, FieldLink> | undefined>(
    undefined,
  );
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [tokens, setTokens] = useState<CanvasTokens | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [hoverCard, setHoverCard] = useState<{
    pointId: number;
    x: number;
    y: number;
  } | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Zoom is tracked in state so the LOD (blobs-far/points-near) + mini-map
  // viewport re-render on camera moves; the painter reads the live globalScale.
  const [zoom, setZoom] = useState(1);
  // While the camera is actively panning/zooming, the hover card is suppressed
  // so it never chases the cursor mid-gesture (research §1.5).
  const gesturingUntil = useRef(0);

  const labelAlpha = useRef(new Map<number, number>());
  const lastFrameAt = useRef(0);
  const placedLabels = useRef<PlacedLabel[]>([]);
  const didFit = useRef(false);

  useCanvasWheel(containerRef, fgRef);

  const pointById = useMemo(() => {
    const m = new Map<number, FieldRenderPoint>();
    for (const p of points) m.set(p.id, p);
    return m;
  }, [points]);

  // `zoom` state exists to re-render on camera zoom (mini-map + hover gating);
  // the painters read the live globalScale directly for LOD.
  void zoom;

  // Cluster blobs for the far-zoom aggregate view (G7).
  const blobs = useMemo(() => clusterBlobs(points), [points]);

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
    const k = fg.zoom();
    if (center && k) {
      fg.centerAt(
        center.x + delta / (2 * k),
        center.y,
        reducedMotion ? 0 : 300,
      );
    }
  }, [rightInset, reducedMotion]);

  // G5 — fly-to (search-to-focus): glide the camera to the searched track and
  // pop a zoom that resolves it, once per nonce.
  const lastFlyNonce = useRef(0);
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !shouldFireFlyTo(flyTo, lastFlyNonce.current)) return;
    lastFlyNonce.current = flyTo?.nonce ?? 0;
    const target = graphData.nodes.find((n) => n.id === flyTo?.id);
    if (!target || target.x === undefined || target.y === undefined) return;
    const duration = reducedMotion ? 0 : FLY_TO_MS;
    fg.centerAt(target.x, target.y, duration);
    if (fg.zoom() < 2) fg.zoom(2, duration);
    onSelect(target.id);
  }, [flyTo, graphData, reducedMotion, onSelect]);

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

  /**
   * G7 — cluster blobs for the far-zoom aggregate. Below the LOD threshold the
   * 5,862-point cloud collapses into one soft disc per cluster (its colour, its
   * id), so the field is a legible drill-down instead of a fog. Cross-fades out
   * as the points fade in.
   */
  function paintBlobs(ctx: CanvasRenderingContext2D, globalScale: number) {
    if (!tokens) return;
    const l = fieldLod(globalScale);
    if (l.blobOpacity <= 0.01) return;
    ctx.save();
    ctx.globalAlpha = l.blobOpacity;
    for (const blob of blobs) {
      ctx.beginPath();
      ctx.arc(blob.x, blob.y, blob.radius, 0, 2 * Math.PI);
      ctx.fillStyle = blob.fill;
      ctx.globalAlpha = l.blobOpacity * 0.4;
      ctx.fill();
      ctx.globalAlpha = l.blobOpacity;
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = blob.fill;
      ctx.stroke();
      ctx.font = `400 13px ${tokens.fontData}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = tokens.textSecondary;
      ctx.fillText(`C${blob.cluster}`, blob.x, blob.y);
    }
    ctx.restore();
  }

  function paintPoint(
    node: FieldNode,
    ctx: CanvasRenderingContext2D,
    globalScale: number,
  ) {
    if (!tokens || node.x === undefined || node.y === undefined) return;
    // G7 LOD: far out, points are fully faded and the blob layer carries the
    // field; keep hovered/selected points visible so interaction still works.
    const hovered = node.id === hoveredId;
    const selected = node.id === selectedId;
    const pointAlpha = fieldLod(globalScale).pointOpacity;
    if (pointAlpha <= 0.01 && !hovered && !selected) return;

    ctx.save();
    ctx.globalAlpha = hovered || selected ? 1 : pointAlpha;
    drawDisc(ctx, node, hovered, selected, tokens);
    ctx.restore();
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

  // G1 — hover card on dwell. Points are only resolvable once zoomed in, so the
  // card is gated behind the point-visible LOD zoom too; hidden mid-gesture.
  const handleHover = useCallback((node: FieldNode | null) => {
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
      if (fieldLod(fg.zoom() ?? 1).pointOpacity < 0.5) return;
      const screen = fg.graph2ScreenCoords(node.x, node.y);
      setHoverCard({ pointId: node.id, x: screen.x, y: screen.y });
    }, HOVER_CARD_DELAY_MS);
  }, []);

  const getViewExtent = useCallback(() => {
    const fg = fgRef.current;
    if (!fg || size.width === 0) return null;
    const tl = fg.screen2GraphCoords(0, 0);
    const br = fg.screen2GraphCoords(size.width, size.height);
    return { minX: tl.x, minY: tl.y, maxX: br.x, maxY: br.y };
  }, [size.width, size.height]);

  const hoveredPoint = hoverCard ? pointById.get(hoverCard.pointId) : null;
  const hoveredCardModel: TrackCardModel | null = hoveredPoint
    ? {
        kind: "track",
        title: hoveredPoint.name,
        subtitle: hoveredPoint.artist,
        imageUrl: hoveredPoint.albumImageUrl,
        clusterId: hoveredPoint.cluster >= 0 ? hoveredPoint.cluster : null,
        playlistCount: hoveredPoint.playlistCount,
        fingerprint: hoveredPoint.features
          ? fingerprintBars(hoveredPoint.features)
          : null,
      }
    : null;

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
          enableZoomInteraction={false}
          onNodeHover={handleHover}
          onNodeClick={(node) => onSelect(node.id)}
          onBackgroundClick={() => onSelect(null)}
          onZoom={(t) => {
            setZoom(t.k);
            gesturingUntil.current = performance.now() + 220;
            setHoverCard(null);
          }}
          onRenderFramePre={(ctx, globalScale) => {
            placedLabels.current = [];
            paintHulls(ctx);
            paintBlobs(ctx, globalScale);
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
      {hoveredPoint && hoverCard && hoveredCardModel && (
        <TrackHoverCard
          model={hoveredCardModel}
          color={parseOklch(hoveredPoint.fill)}
          x={hoverCard.x}
          y={hoverCard.y}
          containerWidth={size.width}
          containerHeight={size.height}
          rightInset={rightInset}
        />
      )}
      {graphMounted && points.length > 0 && (
        <CanvasMinimap points={points} getViewExtent={getViewExtent} />
      )}
    </div>
  );
}
