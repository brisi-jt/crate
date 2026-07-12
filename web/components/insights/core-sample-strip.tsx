"use client";

import { useMemo } from "react";
import type { AddsOverTime } from "@/lib/api/schemas";
import {
  axisTickIndices,
  coreBands,
  formatCoreMonth,
} from "@/lib/insights/core-sample";

interface CoreSampleStripProps {
  adds: AddsOverTime[];
  width?: number;
  height?: number;
}

/**
 * The adds-over-time reading as a geological core sample. Time runs left to
 * right; each month is a sediment band tinted by the acoustic centroid of what
 * was added that month, its height encoding add volume. Grey bands = adds with
 * no enriched color yet. A sparse month axis anchors the timeline.
 */
export function CoreSampleStrip({
  adds,
  width = 380,
  height = 84,
}: CoreSampleStripProps) {
  const bands = useMemo(() => coreBands(adds), [adds]);

  if (bands.length === 0) {
    return (
      <span className="micro-caps text-text-muted">NO ADD HISTORY YET</span>
    );
  }

  const stripH = height - 16;
  const bandW = width / bands.length;
  const ticks = new Set(axisTickIndices(bands.length, 5));

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Adds over time core sample"
    >
      <title>Curation timeline colored by what you added each month</title>
      {bands.map((band, i) => {
        const bh = Math.max(2, band.intensity * stripH);
        const x = i * bandW;
        return (
          <rect
            key={band.month}
            x={x}
            y={stripH - bh}
            width={bandW + 0.5}
            height={bh}
            fill={band.colorString}
            fillOpacity={band.unenriched ? 0.4 : 0.85}
          />
        );
      })}
      {/* baseline */}
      <line
        x1={0}
        y1={stripH}
        x2={width}
        y2={stripH}
        stroke="var(--border-subtle)"
        strokeWidth={0.5}
      />
      {bands.map((band, i) =>
        ticks.has(i) ? (
          <text
            key={`tick-${band.month}`}
            x={i * bandW + bandW / 2}
            y={height - 3}
            textAnchor="middle"
            className="data-readout"
            fontSize={8}
            fill="var(--text-muted)"
          >
            {formatCoreMonth(band.month)}
          </text>
        ) : null,
      )}
    </svg>
  );
}
