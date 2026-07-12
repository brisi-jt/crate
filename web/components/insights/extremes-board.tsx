"use client";

import type { Extreme } from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

interface ExtremesBoardProps {
  extremes: Extreme[];
}

/** "most_energy" → "MOST ENERGY". */
function humanLabel(label: string): string {
  return label.replace(/_/g, " ").toUpperCase();
}

function formatValue(extreme: Extreme): string {
  if (extreme.unit === "seconds") {
    const total = Math.round(extreme.value);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  // percentile
  return `P${Math.round(extreme.value * 100)}`;
}

/**
 * The superlatives ledger — longest, shortest, most-X. Each row is a
 * click-to-open track deep-link: selecting it opens the track panel (which
 * flies the map / offers playback). Instrument rows, no card theatre.
 */
export function ExtremesBoard({ extremes }: ExtremesBoardProps) {
  const openTrack = useUiStore((s) => s.openTrack);

  if (extremes.length === 0) {
    return <span className="micro-caps text-text-muted">NO EXTREMES YET</span>;
  }

  return (
    <div className="flex flex-col">
      {extremes.map((extreme) => (
        <button
          key={`${extreme.label}-${extreme.track_id}`}
          type="button"
          onClick={() => openTrack(extreme.track_id)}
          className="flex items-center gap-sm border-border-subtle border-b py-xs text-left last:border-b-0 hover:bg-surface-2"
        >
          <span className="micro-caps w-[120px] shrink-0 text-text-muted">
            {humanLabel(extreme.label)}
          </span>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm text-text-primary">
              {extreme.name}
            </span>
            <span className="truncate text-micro text-text-muted">
              {extreme.artist}
            </span>
          </div>
          <span className="data-readout shrink-0 text-sm text-text-secondary">
            {formatValue(extreme)}
          </span>
        </button>
      ))}
    </div>
  );
}
