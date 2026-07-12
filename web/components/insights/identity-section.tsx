"use client";

import { FingerprintRadial } from "@/components/insights/fingerprint-radial";
import { Readout } from "@/components/panels/right-dock";
import type { InsightsCoverage, TasteIdentity } from "@/lib/api/schemas";

interface IdentitySectionProps {
  identity: TasteIdentity;
  coverage: InsightsCoverage;
}

/** Centroid for the fingerprint fill, reduced from the 9-axis percentiles. */
function centroidFromFingerprint(
  identity: TasteIdentity,
): { acousticness: number; energy: number; valence: number } | null {
  const by = new Map(
    identity.fingerprint.map((f) => [f.feature, f.percentile]),
  );
  const acousticness = by.get("acousticness");
  const energy = by.get("energy");
  const valence = by.get("valence");
  if (
    acousticness === undefined ||
    energy === undefined ||
    valence === undefined
  ) {
    return null;
  }
  return { acousticness, energy, valence };
}

/**
 * TASTE IDENTITY — the survey's signature block: fingerprint radial, the
 * classification stamp in the display face, and the three honest scalars
 * (entropy / effective genres / acoustic sprawl) plus the archetype sub-axes.
 */
export function IdentitySection({ identity, coverage }: IdentitySectionProps) {
  const centroid = centroidFromFingerprint(identity);
  const { genre_entropy, gs_score, typology, genre_rarity } = identity;

  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap items-center gap-xl">
        <FingerprintRadial
          fingerprint={identity.fingerprint}
          centroid={centroid}
        />

        <div className="flex flex-1 flex-col gap-md">
          {/* Classification stamp — the shareable object */}
          <div className="flex flex-col gap-2xs">
            <span className="micro-caps text-text-muted">Classification</span>
            <span className="display-caps text-lg text-text-primary">
              {typology.archetype.toUpperCase()}
            </span>
          </div>

          <div className="flex flex-wrap gap-lg">
            <Readout
              label="Genre entropy"
              value={`${genre_entropy.entropy_bits.toFixed(2)} bits`}
            />
            <Readout
              label="Effective genres"
              value={genre_entropy.effective_genres.toFixed(0)}
            />
            <Readout
              label="Acoustic sprawl"
              value={gs_score !== null ? gs_score.toFixed(2) : "—"}
            />
            <Readout
              label="Mean rarity"
              value={genre_rarity.mean_rarity.toFixed(2)}
            />
          </div>

          {/* Archetype sub-axes as small ticks */}
          <div className="flex flex-col gap-2xs">
            <span className="micro-caps text-text-muted">Archetype axes</span>
            <SubAxis label="Genre breadth" value={typology.genre_breadth} />
            <SubAxis label="Acoustic sprawl" value={typology.acoustic_sprawl} />
            <SubAxis label="Rarity" value={typology.rarity} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-lg">
        <Readout
          label="Enriched tracks"
          value={coverage.enriched_tracks.toLocaleString()}
        />
        <Readout
          label="Library artists"
          value={coverage.library_artists.toLocaleString()}
        />
        <Readout
          label="Total tracks"
          value={coverage.total_tracks.toLocaleString()}
        />
      </div>
    </div>
  );
}

function SubAxis({ label, value }: { label: string; value: number }) {
  const pct = Math.min(1, Math.max(0, value));
  return (
    <div className="flex items-center gap-sm">
      <span className="w-[128px] text-sm text-text-secondary">{label}</span>
      <div className="h-[4px] flex-1 rounded-xs bg-surface-2">
        <div
          className="h-full rounded-xs bg-border-strong"
          style={{ width: `${Math.max(2, pct * 100)}%` }}
        />
      </div>
      <span className="data-readout w-[44px] text-right text-micro text-text-muted">
        {value.toFixed(2)}
      </span>
    </div>
  );
}
