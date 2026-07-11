"use client";

/**
 * Paired-bar feature fingerprint: a percentile bar in the entity's data
 * color with an optional profile tick. Shared by the listening deck
 * (candidate vs playlist) and the track card (track vs its playlists).
 * Labels + P-values keep meaning off hue alone.
 */

export interface FingerprintBarRow {
  key: string;
  label: string;
  /** Bar fill, library percentile 0–1. */
  value: number;
  /** Profile tick position, 0–1; omit to render the bar alone. */
  tick?: number | null;
}

export function FingerprintBars({
  rows,
  valueColor,
  tickColor,
}: {
  rows: FingerprintBarRow[];
  valueColor: string | null;
  tickColor: string | null;
}) {
  return (
    <div className="flex flex-col gap-xs">
      {rows.map(({ key, label, value, tick }) => (
        <div
          key={key}
          className="grid grid-cols-[110px_1fr_42px] items-center gap-sm"
        >
          <span className="micro-caps text-text-muted">{label}</span>
          <div className="relative h-[6px] rounded-xs bg-surface-2">
            <div
              className="h-[6px] rounded-xs"
              style={{
                width: `${Math.round(value * 100)}%`,
                background: valueColor ?? "var(--text-secondary)",
              }}
            />
            {tick !== undefined && tick !== null && (
              <div
                className="absolute top-[-3px] h-[12px] w-[2px]"
                style={{
                  left: `${Math.round(tick * 100)}%`,
                  background: tickColor ?? "var(--text-secondary)",
                }}
              />
            )}
          </div>
          <span className="data-readout text-right text-micro text-text-secondary">
            P{Math.round(value * 100)}
          </span>
        </div>
      ))}
    </div>
  );
}
