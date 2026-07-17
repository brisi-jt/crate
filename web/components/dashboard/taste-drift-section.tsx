"use client";

import { Explain } from "@/components/explain/explain";
import { DeltaStrip } from "@/components/insights/extended/extended-kit";
import type { TasteDrift } from "@/lib/api/schemas-competitive";
import { driftAxesSorted } from "@/lib/competitive/dashboard-view";

function formatCaptured(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

/**
 * F5 — taste drift. A timeline of past top-track readings (only track readings
 * are comparable — artist readings carry no audio), and a feature-by-feature
 * comparison of the selected past self against the current library.
 */
export function TasteDriftSection({
  data,
  selectedSnapshotId,
  onSelect,
}: {
  data: TasteDrift;
  selectedSnapshotId: number | null;
  onSelect: (snapshotId: number | null) => void;
}) {
  const comparable = data.timeline.filter((t) => t.comparable);

  if (comparable.length === 0) {
    return (
      <p className="max-w-[56ch] text-sm text-text-secondary">
        No comparable past readings yet. Top-track readings accrue over time;
        once there's one to compare against, your drift shows here.
      </p>
    );
  }

  const comparison = data.comparison;

  return (
    <div className="flex flex-col gap-lg">
      {/* Timeline picker — comparable readings only */}
      <div className="flex flex-col gap-xs">
        <Explain metric="taste_drift">
          <span className="micro-caps text-text-muted">
            Compare against a past reading
          </span>
        </Explain>
        <div className="flex flex-wrap gap-xs">
          {comparable.map((entry) => (
            <button
              key={entry.snapshot_id}
              type="button"
              onClick={() =>
                onSelect(
                  selectedSnapshotId === entry.snapshot_id
                    ? null
                    : entry.snapshot_id,
                )
              }
              aria-pressed={selectedSnapshotId === entry.snapshot_id}
              className={`micro-caps cursor-pointer rounded-xs border px-sm py-2xs ${
                selectedSnapshotId === entry.snapshot_id
                  ? "border-amber text-amber"
                  : "border-border-subtle text-text-muted hover:text-text-secondary"
              }`}
            >
              {entry.time_range} · {formatCaptured(entry.captured_at)}
            </button>
          ))}
        </div>
      </div>

      {/* Comparison */}
      {comparison ? (
        <div className="flex flex-col gap-md">
          <div className="flex flex-wrap items-end gap-xl">
            <div className="flex flex-col gap-2xs">
              <span className="micro-caps text-text-muted">Distance moved</span>
              <span className="data-readout text-lg text-text-primary">
                {comparison.distance.toFixed(3)}
              </span>
            </div>
            <div className="flex flex-col gap-2xs">
              <span className="micro-caps text-text-muted">Biggest mover</span>
              <span className="data-readout text-lg text-text-primary">
                {comparison.biggest_mover.feature}{" "}
                {comparison.biggest_mover.delta >= 0 ? "+" : ""}
                {comparison.biggest_mover.delta.toFixed(2)}
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-xs">
            <span className="micro-caps text-text-muted">
              Now vs then — per feature
            </span>
            <DeltaStrip axes={driftAxesSorted(comparison.axes)} />
          </div>
        </div>
      ) : (
        <p className="text-sm text-text-muted">
          Pick a reading above to see how your sound has shifted since then.
        </p>
      )}
    </div>
  );
}
