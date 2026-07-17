"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import {
  DeltaStrip,
  ExtendedEmpty,
  NameLine,
} from "@/components/insights/extended/extended-kit";
import type { SavedSection } from "@/lib/api/schemas-extended";
import { formatRate } from "@/lib/insights/extended-view";

/**
 * SAVED SONGS — the shape of your Liked Songs against your filed library: the
 * inbox you forgot (orphans), how the sound differs, how long saves wait before
 * you file them, and how much you later un-like.
 */
export function SavedInsightsSection({ saved }: { saved: SavedSection }) {
  if (saved.total_saved === 0) {
    return (
      <ExtendedEmpty note="No saved songs found. Your Liked Songs power this reading — the inbox of orphans, the save-to-file wait, and how your likes sound against your playlists." />
    );
  }

  const { orphan_saves, save_file_latency, unsave_churn, liked_vs_playlist } =
    saved;

  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap gap-lg">
        <ExplainReadout
          metric="orphan_saves"
          label="Orphan saves"
          value={orphan_saves.orphan_count.toLocaleString()}
        />
        <ExplainReadout
          metric="save_file_latency"
          label="Save-to-file"
          value={
            save_file_latency.median_days !== null
              ? `${save_file_latency.median_days.toFixed(0)} d`
              : "—"
          }
        />
        <ExplainReadout
          metric="unsave_churn"
          label="Unsave churn"
          value={formatRate(unsave_churn.churn_rate)}
        />
      </div>

      {liked_vs_playlist.axes.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="liked_vs_playlist">
            <span className="micro-caps text-text-muted">
              Liked vs playlist sound — per trait
            </span>
          </Explain>
          <DeltaStrip axes={liked_vs_playlist.axes} />
        </div>
      )}

      {orphan_saves.orphans.length > 0 && (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">
            A few orphans — liked, filed nowhere
          </span>
          <div className="flex flex-col gap-2xs">
            {orphan_saves.orphans.slice(0, 6).map((t) => (
              <NameLine key={t.track_id} title={t.name} subtitle={t.artist} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
