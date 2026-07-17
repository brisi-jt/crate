"use client";

import { Explain } from "@/components/explain/explain";
import { NotYetComputed } from "@/components/panels/right-dock";
import { useQualityPlaylists } from "@/hooks/api/use-competitive";
import { qualitySubscorePercent } from "@/lib/competitive/dashboard-view";

/**
 * F6 — the per-playlist quality breakdown: a headline score and its four
 * explained sub-scores (cohesion, uniqueness, freshness, flow). Each sub-score
 * carries its own explain via the ref the api emits.
 */
export function QualityTab({ playlistId }: { playlistId: number }) {
  const quality = useQualityPlaylists();

  if (quality.isPending) {
    return <div className="h-[120px] animate-pulse rounded-md bg-surface-2" />;
  }
  if (quality.isError || !quality.data) {
    return (
      <div className="flex flex-col items-start gap-xs">
        <span className="micro-caps text-danger">QUALITY UNAVAILABLE</span>
        <button
          type="button"
          onClick={() => quality.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  const entry = quality.data.playlists.find(
    (p) => p.playlist_id === playlistId,
  );
  if (!entry || entry.score === null) {
    return <NotYetComputed what="Quality score" />;
  }

  return (
    <div className="flex flex-col gap-lg">
      <div className="flex items-end gap-xl">
        <div className="flex flex-col gap-2xs">
          <span className="micro-caps text-text-muted">Quality</span>
          <span className="data-readout text-2xl text-text-primary">
            {qualitySubscorePercent(entry.score)}
          </span>
        </div>
        <span className="data-readout pb-1 text-micro text-text-muted">
          / 100
        </span>
      </div>

      <div className="flex flex-col gap-sm">
        {entry.subscores.map((sub) => (
          <div key={sub.ref} className="flex items-center gap-sm">
            <Explain metric={sub.ref}>
              <span className="micro-caps w-[110px] text-text-muted capitalize">
                {sub.label}
              </span>
            </Explain>
            <div className="h-[6px] flex-1 rounded-xs bg-surface-2">
              <div
                className="h-full rounded-xs bg-border-strong"
                style={{ width: `${Math.max(2, sub.value * 100)}%` }}
              />
            </div>
            <span className="data-readout w-[42px] text-right text-micro text-text-secondary">
              {qualitySubscorePercent(sub.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
