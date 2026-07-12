"use client";

import type { AbandonedPlaylist } from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

interface DormancyListProps {
  playlists: AbandonedPlaylist[];
}

/**
 * Abandoned playlists — the dusty ones, dustiest first. Each row deep-links
 * into its playlist panel. Quiet list, no warning theatre — just the last-
 * touched readout (design principle: dust, not alarm).
 */
export function DormancyList({ playlists }: DormancyListProps) {
  const openPlaylist = useUiStore((s) => s.openPlaylist);
  const setMapMode = useUiStore((s) => s.setMapMode);

  if (playlists.length === 0) {
    return (
      <span className="micro-caps text-text-muted">
        NOTHING DORMANT — every playlist has moved recently
      </span>
    );
  }

  return (
    <div className="flex flex-col">
      {playlists.map((p) => (
        <button
          key={p.playlist_id}
          type="button"
          onClick={() => {
            setMapMode("playlists");
            openPlaylist(p.playlist_id);
          }}
          className="flex items-center gap-sm border-border-subtle border-b py-xs text-left last:border-b-0 hover:bg-surface-2"
        >
          <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
            {p.name}
          </span>
          <span className="data-readout shrink-0 text-micro text-text-muted">
            {p.months_dormant} MO DORMANT
          </span>
        </button>
      ))}
    </div>
  );
}
