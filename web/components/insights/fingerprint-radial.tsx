"use client";

import { useMemo } from "react";
import type { FingerprintAxis } from "@/lib/api/schemas";
import { acousticColor, GREY_NODE, oklchString } from "@/lib/color/acoustic";
import {
  fingerprintSpokes,
  polar,
  polygonPoints,
} from "@/lib/insights/fingerprint";

interface FingerprintRadialProps {
  fingerprint: FingerprintAxis[];
  /** Library centroid — fills the polygon with the library's own sound. */
  centroid: { acousticness: number; energy: number; valence: number } | null;
  size?: number;
}

const RINGS = [0.25, 0.5, 0.75, 1];

/**
 * The acoustic fingerprint as a nine-spoke radial — the page's signature
 * object. Percentile ticks per feature, a polygon filled with the library's
 * centroid color, concentric percentile rings for reference. Pure SVG, OKLCH.
 */
export function FingerprintRadial({
  fingerprint,
  centroid,
  size = 260,
}: FingerprintRadialProps) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 34; // room for the ring labels

  const spokes = useMemo(
    () => fingerprintSpokes(fingerprint, cx, cy, radius),
    [fingerprint, cx, cy, radius],
  );

  const fill = centroid ? acousticColor(centroid) : GREY_NODE;
  const fillString = oklchString(fill);

  if (spokes.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-md border border-border-subtle border-dashed"
        style={{ width: size, height: size }}
      >
        <span className="micro-caps max-w-[70%] text-center text-text-muted">
          FINGERPRINT PENDING · needs enriched features
        </span>
      </div>
    );
  }

  const poly = polygonPoints(spokes);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="Acoustic fingerprint radial"
    >
      <title>
        Acoustic fingerprint — nine features at their library percentiles
      </title>

      {/* Percentile reference rings */}
      {RINGS.map((r) => (
        <circle
          key={r}
          cx={cx}
          cy={cy}
          r={radius * r}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth={r === 1 ? 1 : 0.5}
        />
      ))}

      {/* Spokes */}
      {spokes.map((s) => (
        <line
          key={`spoke-${s.feature}`}
          x1={cx}
          y1={cy}
          x2={s.outer.x}
          y2={s.outer.y}
          stroke="var(--border-subtle)"
          strokeWidth={0.5}
        />
      ))}

      {/* The filled polygon — the library's sound as a shape */}
      <polygon
        points={poly}
        fill={fillString}
        fillOpacity={0.28}
        stroke={fillString}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />

      {/* Percentile ticks + axis labels */}
      {spokes.map((s) => {
        const labelPt = polar(cx, cy, radius + 16, s.angle);
        return (
          <g key={`tick-${s.feature}`}>
            <circle cx={s.point.x} cy={s.point.y} r={2.5} fill={fillString} />
            <text
              x={labelPt.x}
              y={labelPt.y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="data-readout"
              fontSize={9}
              fill="var(--text-muted)"
            >
              {s.label}
            </text>
          </g>
        );
      })}

      {/* Centroid core */}
      <circle cx={cx} cy={cy} r={3} fill={fillString} />
    </svg>
  );
}
