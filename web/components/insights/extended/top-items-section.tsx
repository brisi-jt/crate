"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import {
  DeltaStrip,
  ExtendedEmpty,
} from "@/components/insights/extended/extended-kit";
import type { TopItemsSection } from "@/lib/api/schemas-extended";
import { formatRate } from "@/lib/insights/extended-view";

/**
 * TOP ITEMS — how your active favourites diverge from the collection at large:
 * the sound of your top tracks vs the library, how much your top artists turn
 * over, and which favourites are rising vs settled.
 */
export function TopItemsInsightsSection({
  topItems,
}: {
  topItems: TopItemsSection;
}) {
  if (topItems.snapshot_count === 0) {
    return (
      <ExtendedEmpty note="No top-items readings captured yet. Once your Spotify affinity charts are recorded over time, this compares your active favourites against your whole library." />
    );
  }

  const { top_vs_library, affinity_churn, short_vs_long } = topItems;

  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap gap-lg">
        <ExplainReadout
          metric="affinity_churn"
          label="Artist overlap"
          value={formatRate(affinity_churn.mean_jaccard)}
        />
        <ExplainReadout
          metric="short_vs_long"
          label="Rising now"
          value={short_vs_long.rising.length.toLocaleString()}
        />
      </div>

      {top_vs_library.axes.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="top_vs_library">
            <span className="micro-caps text-text-muted">
              Top tracks vs library — per trait
            </span>
          </Explain>
          <DeltaStrip axes={top_vs_library.axes} />
        </div>
      )}

      {(short_vs_long.rising.length > 0 || short_vs_long.fading.length > 0) && (
        <div className="flex flex-wrap gap-xl">
          <div className="flex flex-col gap-2xs">
            <span className="micro-caps text-text-muted">
              Rising — {short_vs_long.rising.length}
            </span>
            <span className="max-w-[24ch] text-sm text-text-secondary">
              New obsessions in your short-term rotation.
            </span>
          </div>
          <div className="flex flex-col gap-2xs">
            <span className="micro-caps text-text-muted">
              Fading — {short_vs_long.fading.length}
            </span>
            <span className="max-w-[24ch] text-sm text-text-secondary">
              Cooling off from your long-run favourites.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
