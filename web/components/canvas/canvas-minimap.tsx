"use client";

import { useEffect, useRef } from "react";
import { minimapLayout, viewportRect } from "@/lib/canvas/minimap";
import { readCanvasTokens } from "@/lib/graph/canvas-tokens";

/**
 * Corner mini-map. A small overview of the whole field with the current
 * camera viewport marked, so a dense field (5,862 → 40k points) is orientable.
 * Drawn on its own tiny canvas from the field's graph-space points + the live
 * camera extent (polled on a RAF while mounted).
 */

const BOX = { width: 132, height: 92 };
const DOT = 0.6;

interface CameraLike {
  screen2GraphCoords: (x: number, y: number) => { x: number; y: number };
}

interface CanvasMinimapProps {
  points: Array<{ x: number; y: number; fill: string }>;
  /** Reads the current camera extent each frame. Null → viewport rect hidden. */
  getViewExtent: () => {
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
  } | null;
  /** Bottom offset in px so it clears the field guide / legend. */
  bottomOffset?: number;
}

export function CanvasMinimap({
  points,
  getViewExtent,
  bottomOffset = 96,
}: CanvasMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = BOX.width * dpr;
    canvas.height = BOX.height * dpr;
    ctx.scale(dpr, dpr);

    const tokens = readCanvasTokens();
    const layout = minimapLayout(points, BOX);
    let raf = 0;

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, BOX.width, BOX.height);
      // Points as a faint dust cloud.
      for (const p of points) {
        const q = layout.project(p.x, p.y);
        ctx.fillStyle = p.fill;
        ctx.globalAlpha = 0.5;
        ctx.beginPath();
        ctx.arc(q.x, q.y, DOT, 0, 2 * Math.PI);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      // Viewport rect.
      const ext = getViewExtent();
      if (ext) {
        const rect = viewportRect(layout, ext);
        ctx.strokeStyle = tokens.textSecondary;
        ctx.lineWidth = 1;
        ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);
      }
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [points, getViewExtent]);

  return (
    <div
      className="pointer-events-none absolute right-lg z-10 overflow-hidden rounded-sm border border-border-subtle bg-surface-1/80"
      style={{ width: BOX.width, height: BOX.height, bottom: bottomOffset }}
    >
      <canvas
        ref={canvasRef}
        style={{ width: BOX.width, height: BOX.height }}
      />
    </div>
  );
}

export type { CameraLike };
