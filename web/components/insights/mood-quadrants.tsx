"use client";

import type { Mood } from "@/lib/api/schemas";

interface MoodQuadrantsProps {
  mood: Mood;
  size?: number;
}

/** Quadrant labels at their (valence, energy) corner. */
const QUADRANTS = [
  { key: "happy_energetic", label: "HAPPY · ENERGETIC", corner: "top-right" },
  { key: "energetic_tense", label: "TENSE · ENERGETIC", corner: "top-left" },
  {
    key: "peaceful_content",
    label: "PEACEFUL · CONTENT",
    corner: "bottom-right",
  },
  { key: "calm_sad", label: "CALM · SAD", corner: "bottom-left" },
] as const;

/**
 * Energy × valence mood density. The grid is size×size counts
 * (grid[valence band][energy band]); each cell shades by its share of the
 * busiest cell, tinted toward the acoustic color of that region — high
 * valence brighter, high energy more chromatic. Quadrant shares annotate the
 * four corners.
 */
export function MoodQuadrants({ mood, size = 220 }: MoodQuadrantsProps) {
  const n = mood.size;
  const cell = size / n;
  const maxCell = mood.grid.reduce((m, row) => Math.max(m, ...row), 0);

  // Flatten into positioned cells with a stable coordinate key. vi = valence
  // band (0 = low → bottom), ei = energy band (0 = low → left).
  const cells = mood.grid.flatMap((row, vi) =>
    row.map((count, ei) => {
      const valence = (vi + 0.5) / n;
      const energy = (ei + 0.5) / n;
      const share = maxCell > 0 ? count / maxCell : 0;
      return {
        key: `v${vi}-e${ei}`,
        x: ei * cell,
        y: size - (vi + 1) * cell,
        fill: `oklch(${(0.4 + 0.3 * valence).toFixed(3)} ${(0.03 + 0.14 * energy).toFixed(3)} ${(70 - 150 * energy).toFixed(1)})`,
        opacity: 0.12 + 0.85 * share,
      };
    }),
  );

  return (
    <div className="flex flex-col gap-sm">
      <div
        className="relative rounded-sm border border-border-subtle"
        style={{ width: size, height: size }}
      >
        <svg width={size} height={size} role="img" aria-label="Mood quadrants">
          <title>Energy by valence mood density</title>
          {cells.map((c) => (
            <rect
              key={c.key}
              x={c.x}
              y={c.y}
              width={cell + 0.5}
              height={cell + 0.5}
              fill={c.fill}
              fillOpacity={c.opacity}
            />
          ))}
          {/* Crosshair at the 0.5 midpoint */}
          <line
            x1={size / 2}
            y1={0}
            x2={size / 2}
            y2={size}
            stroke="var(--border-subtle)"
            strokeWidth={0.75}
          />
          <line
            x1={0}
            y1={size / 2}
            x2={size}
            y2={size / 2}
            stroke="var(--border-subtle)"
            strokeWidth={0.75}
          />
        </svg>
        <span className="micro-caps -translate-x-1/2 absolute bottom-[-18px] left-1/2 text-text-muted">
          ENERGY →
        </span>
        <span className="micro-caps -rotate-90 absolute top-1/2 left-[-30px] origin-center text-text-muted">
          VALENCE →
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2xs">
        {QUADRANTS.map((q) => (
          <div key={q.key} className="flex items-center justify-between gap-sm">
            <span className="micro-caps text-text-muted">{q.label}</span>
            <span className="data-readout text-micro text-text-secondary">
              {mood.shares[q.key] !== undefined
                ? `${(mood.shares[q.key] * 100).toFixed(0)}%`
                : "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
