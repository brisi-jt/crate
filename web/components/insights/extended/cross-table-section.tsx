"use client";

import { Explain } from "@/components/explain/explain";
import {
  BarRow,
  ExtendedEmpty,
  NameLine,
} from "@/components/insights/extended/extended-kit";
import type { CrossTableSection } from "@/lib/api/schemas-extended";

/**
 * CROSS-CUTTING — readings that join tables: playlists you still secretly play
 * vs truly-neglected ones, how each trait's spread has moved, and whether your
 * adds chase new releases or dig into the past.
 */
export function CrossTableInsightsSection({
  cross,
}: {
  cross: CrossTableSection;
}) {
  const { listened_vs_neglected, calibration_drift, era_add_vs_release } =
    cross;

  const empty =
    listened_vs_neglected.length === 0 &&
    era_add_vs_release.total === 0 &&
    calibration_drift.features.length === 0;
  if (empty) {
    return (
      <ExtendedEmpty note="Nothing to cross yet. Once you have playlists, plays, and dated tracks, this reveals your quiet-but-loved playlists and your nostalgia waves." />
    );
  }

  const stillPlayed = listened_vs_neglected.filter(
    (p) => !p.neglected && p.plays > 0,
  );
  const trulyNeglected = listened_vs_neglected.filter((p) => p.neglected);
  const maxGap = Math.max(
    1,
    ...era_add_vs_release.add_years.map((y) => y.median_gap_years),
  );

  return (
    <div className="flex flex-col gap-lg">
      {stillPlayed.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="listened_vs_neglected">
            <span className="micro-caps text-text-muted">
              Quiet, but you still play them
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {stillPlayed.slice(0, 5).map((p) => (
              <NameLine
                key={p.playlist_id}
                title={p.name}
                trailing={`${p.plays} plays · ${p.months_dormant}mo dormant`}
              />
            ))}
          </div>
        </div>
      )}

      {trulyNeglected.length > 0 && (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">
            Truly neglected — dormant and unplayed
          </span>
          <div className="flex flex-col gap-2xs">
            {trulyNeglected.slice(0, 5).map((p) => (
              <NameLine
                key={p.playlist_id}
                title={p.name}
                trailing={`${p.months_dormant}mo`}
              />
            ))}
          </div>
        </div>
      )}

      {era_add_vs_release.add_years.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="era_add_vs_release">
            <span className="micro-caps text-text-muted">
              Nostalgia waves — median gap by add year
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {era_add_vs_release.add_years.map((y) => (
              <BarRow
                key={y.add_year}
                label={String(y.add_year)}
                fraction={y.median_gap_years / maxGap}
                value={`${y.median_gap_years.toFixed(0)}y`}
              />
            ))}
          </div>
        </div>
      )}

      {calibration_drift.features.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="calibration_drift">
            <span className="micro-caps text-text-muted">
              Trait spread — per feature
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {calibration_drift.features.map((f) => {
              const spread = f.points.at(-1)?.spread ?? 0;
              return (
                <div key={f.feature} className="flex items-center gap-sm">
                  <span className="w-[120px] truncate text-sm text-text-secondary">
                    {f.feature}
                  </span>
                  <div className="h-[4px] flex-1 rounded-xs bg-surface-2">
                    <div
                      className="h-full rounded-xs bg-border-strong"
                      style={{ width: `${Math.max(2, spread * 100)}%` }}
                    />
                  </div>
                  <span className="data-readout w-[64px] text-right text-micro text-text-muted">
                    {spread.toFixed(2)}
                    {f.spread_delta !== null && f.spread_delta !== 0
                      ? ` ${f.spread_delta > 0 ? "▲" : "▼"}`
                      : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
