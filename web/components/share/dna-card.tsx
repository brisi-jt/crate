"use client";

import type { AcousticCentroid } from "@/lib/color/acoustic";
import { acousticColor, GREY_NODE, oklchString } from "@/lib/color/acoustic";
import { auraCentroid, topGenreLabels } from "@/lib/share/card-view";
import { personalityLabel } from "@/lib/share/personality";

export interface DnaCardData {
  /** Playlist/track centroids to average into the sound aura. */
  centroids: Array<AcousticCentroid | null>;
  /** Library fingerprint percentiles, keyed by feature. */
  fingerprint: Record<string, number>;
  /** Library obscurity 0..1 (F3). Null when unscored. */
  obscurity: number | null;
  /** Dominant genres, most-present first. */
  topGenres: string[];
  /** Enriched track count, for the subtitle stat. */
  enrichedTracks: number;
}

/**
 * The "crate DNA" body (S1): a large sound-aura swatch from the library's
 * acoustic centroid, a generated personality label, the obscurity flex, and
 * the top genres. Pure presentation — all derivation is in lib/share.
 */
export function DnaCardBody({ data }: { data: DnaCardData }) {
  const aura = auraCentroid(data.centroids);
  const auraColor = oklchString(aura ? acousticColor(aura) : GREY_NODE);
  const label = personalityLabel({
    energy: data.fingerprint.energy ?? 0.5,
    valence: data.fingerprint.valence ?? 0.5,
    acousticness: data.fingerprint.acousticness ?? 0.5,
    danceability: data.fingerprint.danceability ?? 0.5,
    obscurity: data.obscurity ?? 0.5,
    topGenres: data.topGenres,
  });
  const genres = topGenreLabels(data.topGenres, 5);
  const obscurityPct =
    data.obscurity !== null
      ? `${Math.round(data.obscurity * 100)}% niche`
      : "—";

  return (
    <div className="flex flex-col items-center gap-[40px] text-center">
      {/* Sound aura */}
      <div
        className="size-[300px] rounded-full"
        style={{
          background: `radial-gradient(circle at 38% 34%, ${auraColor}, color-mix(in oklch, ${auraColor} 55%, var(--canvas)) 72%, var(--canvas))`,
          boxShadow: `0 0 120px 12px color-mix(in oklch, ${auraColor} 35%, transparent)`,
        }}
      />

      {/* Personality label */}
      <div className="flex flex-col gap-[10px]">
        <span className="micro-caps text-[15px] text-text-muted">
          Your sound signature
        </span>
        <span className="display-caps text-[42px] text-text-primary leading-tight">
          {label}
        </span>
      </div>

      {/* Stat row */}
      <div className="flex items-center gap-[56px]">
        <div className="flex flex-col gap-[4px]">
          <span className="micro-caps text-[13px] text-text-muted">
            Obscurity
          </span>
          <span className="data-readout text-[26px] text-text-primary">
            {obscurityPct}
          </span>
        </div>
        <div className="flex flex-col gap-[4px]">
          <span className="micro-caps text-[13px] text-text-muted">Tracks</span>
          <span className="data-readout text-[26px] text-text-primary">
            {data.enrichedTracks.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Top genres */}
      {genres.length > 0 && (
        <div className="flex max-w-[720px] flex-wrap justify-center gap-[12px]">
          {genres.map((g) => (
            <span
              key={g}
              className="micro-caps rounded-full border border-border-strong px-[18px] py-[8px] text-[15px] text-text-secondary"
            >
              {g}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
