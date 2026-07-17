"use client";

import type { DnaCardData } from "@/components/share/dna-card";
import { DnaCardBody } from "@/components/share/dna-card";
import { ShareButton } from "@/components/share/share-button";
import { useObscurity } from "@/hooks/api/use-competitive";
import { useGraph } from "@/hooks/api/use-graph";
import { useInsights } from "@/hooks/api/use-insights";

/**
 * S1 — the "crate DNA" identity card: sound aura from the library's acoustic
 * centroid, a generated personality label, the obscurity flex, and top genres.
 * Shown as a live preview with a one-tap share export.
 */
export function DnaSection() {
  const graph = useGraph();
  const insights = useInsights();
  const obscurity = useObscurity();

  if (graph.isPending || insights.isPending || obscurity.isPending) {
    return <div className="h-[280px] animate-pulse rounded-md bg-surface-2" />;
  }

  if (!graph.data || !insights.data) {
    return (
      <p className="text-sm text-text-secondary">
        The DNA card reads your enriched library — it fills in once the map and
        survey have computed.
      </p>
    );
  }

  const fingerprint: Record<string, number> = {};
  for (const axis of insights.data.taste_identity.fingerprint) {
    fingerprint[axis.feature] = axis.percentile;
  }

  const data: DnaCardData = {
    centroids: graph.data.nodes.map((n) => n.centroid),
    fingerprint,
    obscurity: obscurity.data?.library.score ?? null,
    topGenres: insights.data.taste_identity.genre_shares.map((g) => g.genre),
    enrichedTracks: graph.data.coverage.enriched_tracks,
  };

  return (
    <div className="flex flex-col gap-md">
      <div className="flex items-center justify-between">
        <span className="micro-caps text-text-muted">Your crate DNA</span>
        <ShareButton kind="dna" title="crate DNA" label="Share DNA">
          <DnaCardBody data={data} />
        </ShareButton>
      </div>
      {/* A scaled-down live preview of the exact card that exports. */}
      <div className="flex justify-center overflow-hidden rounded-md border border-border-subtle bg-canvas p-lg">
        <div className="origin-top scale-[0.52]" style={{ height: 700 }}>
          <div style={{ width: 1080 }} className="flex justify-center">
            <DnaCardBody data={data} />
          </div>
        </div>
      </div>
    </div>
  );
}
