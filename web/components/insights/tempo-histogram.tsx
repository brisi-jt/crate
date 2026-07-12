"use client";

import type { TempoBand } from "@/lib/api/schemas";

interface TempoHistogramProps {
  tempo: TempoBand[];
  width?: number;
  height?: number;
}

/**
 * The BPM spine — raw tempo across fixed width-10 bands [60,200). A metronome
 * ruler with density; the modal band is emphasized. No axis chrome beyond a
 * few tick labels (instrument, not chart-junk).
 */
export function TempoHistogram({
  tempo,
  width = 380,
  height = 120,
}: TempoHistogramProps) {
  const max = tempo.reduce((m, b) => Math.max(m, b.count), 0);
  const total = tempo.reduce((s, b) => s + b.count, 0);
  const modalIdx = tempo.reduce(
    (best, b, i) => (b.count > tempo[best].count ? i : best),
    0,
  );

  if (total === 0) {
    return (
      <span className="micro-caps text-text-muted">NO TEMPO DATA YET</span>
    );
  }

  const barGap = 2;
  const barW = (width - barGap * (tempo.length - 1)) / tempo.length;
  const plotH = height - 18;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Tempo histogram"
    >
      <title>Track tempo distribution in BPM</title>
      {tempo.map((band, i) => {
        const h = max > 0 ? (band.count / max) * plotH : 0;
        const x = i * (barW + barGap);
        const isModal = i === modalIdx;
        return (
          <g key={`${band.bpm_low}`}>
            <rect
              x={x}
              y={plotH - h}
              width={barW}
              height={h}
              rx={1}
              fill={isModal ? "var(--accent-amber)" : "var(--border-strong)"}
              fillOpacity={isModal ? 0.9 : 0.6}
            />
            {(i === 0 || i === tempo.length - 1 || isModal) && (
              <text
                x={x + barW / 2}
                y={height - 4}
                textAnchor="middle"
                className="data-readout"
                fontSize={8}
                fill="var(--text-muted)"
              >
                {band.bpm_low}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
