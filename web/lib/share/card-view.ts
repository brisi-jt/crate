/**
 * Pure view-model helpers for the share-card system (S1/S2). The card itself is
 * an off-screen fixed-size DOM node rendered to a blob by modern-screenshot;
 * everything here is the deterministic data behind it — dimensions, the aura
 * centroid, the OKLCH legend footer, the download filename, genre labels.
 */

import type { AcousticCentroid } from "@/lib/color/acoustic";

/** The vertical story format every share card is laid out at. */
export const CARD_WIDTH = 1080;
export const CARD_HEIGHT = 1350;

/** Slugify a free-form title for a filename. */
function slug(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Zero-padded YYYY-MM-DD in UTC. */
function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/**
 * A stable, dated, kind-tagged download filename:
 *   crate-dna-2026-07-17.png
 *   crate-listening-clock-2026-07-17.png
 */
export function shareFilename(kind: string, date: Date = new Date()): string {
  return `crate-${slug(kind)}-${isoDate(date)}.png`;
}

/**
 * Mean the (non-null) track/playlist centroids into a single acoustic aura —
 * the library's dominant sound, coloured through the same OKLCH law as the map.
 * Null when nothing enriched.
 */
export function auraCentroid(
  centroids: Array<AcousticCentroid | null>,
): AcousticCentroid | null {
  const present = centroids.filter((c): c is AcousticCentroid => c !== null);
  if (present.length === 0) return null;
  const sum = present.reduce(
    (acc, c) => ({
      acousticness: acc.acousticness + c.acousticness,
      energy: acc.energy + c.energy,
      valence: acc.valence + c.valence,
    }),
    { acousticness: 0, energy: 0, valence: 0 },
  );
  const n = present.length;
  return {
    acousticness: sum.acousticness / n,
    energy: sum.energy / n,
    valence: sum.valence / n,
  };
}

export interface LegendItem {
  label: string;
  detail: string;
}

/**
 * The three-axis OKLCH legend for the card footer — the same colour language
 * the app uses everywhere, stated plainly so a shared image carries its own key.
 */
export function legendFooter(): LegendItem[] {
  return [
    { label: "Hue", detail: "organic → electronic" },
    { label: "Intensity", detail: "calm → energetic" },
    { label: "Lightness", detail: "moody → upbeat" },
  ];
}

/** Uppercase, capped list of the top genres for the card. */
export function topGenreLabels(genres: string[], cap: number): string[] {
  return genres.slice(0, cap).map((g) => g.toUpperCase());
}
