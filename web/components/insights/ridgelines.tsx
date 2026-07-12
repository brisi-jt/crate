"use client";

import type { Ridgeline } from "@/lib/api/schemas";

interface RidgelinesProps {
  ridgelines: Ridgeline[];
  width?: number;
}

/** Per-feature hue so each ridge reads as its own axis (not chromatic noise). */
const FEATURE_HUE: Record<string, number> = {
  energy: 300,
  valence: 40,
  danceability: 330,
  acousticness: 70,
  instrumentalness: 150,
  liveness: 190,
  speechiness: 20,
  tempo: 260,
  loudness: 10,
};

const LABELS: Record<string, string> = {
  energy: "ENERGY",
  valence: "VALENCE",
  danceability: "DANCE",
  acousticness: "ACOUSTIC",
  instrumentalness: "INSTRUMENTAL",
  liveness: "LIVENESS",
  speechiness: "SPEECHINESS",
  tempo: "TEMPO",
  loudness: "LOUDNESS",
};

/**
 * Feature-distribution ridgelines — each of the nine features' 20-bucket
 * percentile histogram as a filled area, stacked. Means hide bimodality;
 * these show the shape. Each ridge tinted by its feature's hue.
 */
export function Ridgelines({ ridgelines, width = 380 }: RidgelinesProps) {
  const rowH = 30;
  const overlap = 8; // ridges overlap slightly for a joyplot feel
  const height = ridgelines.length * (rowH - overlap) + overlap + 6;

  if (ridgelines.length === 0) {
    return (
      <span className="micro-caps text-text-muted">NO DISTRIBUTIONS YET</span>
    );
  }

  const labelW = 92;
  const plotW = width - labelW;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Feature distribution ridgelines"
    >
      <title>Distribution shape of each acoustic feature</title>
      {ridgelines.map((ridge, i) => {
        const max = ridge.buckets.reduce((m, b) => Math.max(m, b), 0) || 1;
        const baseY = i * (rowH - overlap) + rowH;
        const hue = FEATURE_HUE[ridge.feature] ?? 265;
        const stroke = `oklch(0.7 0.12 ${hue})`;
        const fill = `oklch(0.7 0.12 ${hue})`;

        const n = ridge.buckets.length;
        const points = ridge.buckets.map((b, bi) => {
          const x = labelW + (bi / (n - 1)) * plotW;
          const y = baseY - (b / max) * rowH;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        });
        const area = `M ${labelW},${baseY} L ${points.join(" L ")} L ${labelW + plotW},${baseY} Z`;

        return (
          <g key={ridge.feature}>
            <path
              d={area}
              fill={fill}
              fillOpacity={0.22}
              stroke={stroke}
              strokeWidth={1}
            />
            <text
              x={0}
              y={baseY - 2}
              className="data-readout"
              fontSize={8.5}
              fill="var(--text-muted)"
            >
              {LABELS[ridge.feature] ?? ridge.feature.toUpperCase()}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
