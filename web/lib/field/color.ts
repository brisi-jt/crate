/**
 * Track-field point color — the acoustic mapping, fed from the best source
 * available (color is evidence, one formula everywhere):
 *
 * 1. Per-track feature percentiles, when the map payload ships them.
 * 2. Otherwise the mean centroid of the playlists holding the track — the
 *    "playlist-colored" scatter. Single-membership tracks land on
 *    exactly their playlist's color; multi-membership tracks blend in
 *    centroid space (never in color space) before mapping.
 * 3. No membership or no enriched owner → the grey out-of-gamut state.
 */

import type { AcousticCentroid } from "@/lib/color/acoustic";
import { acousticColor, GREY_NODE, type Oklch } from "@/lib/color/acoustic";
import type { ClusterPalette, Equalizer } from "@/lib/color/equalize";
import { equalizedColor } from "@/lib/color/equalize";
import type { PaletteMode } from "@/lib/store/ui";

export function meanCentroid(
  centroids: Array<AcousticCentroid | null>,
): AcousticCentroid | null {
  const known = centroids.filter((c): c is AcousticCentroid => c !== null);
  if (known.length === 0) return null;
  const sum = known.reduce(
    (acc, c) => ({
      acousticness: acc.acousticness + c.acousticness,
      energy: acc.energy + c.energy,
      valence: acc.valence + c.valence,
    }),
    { acousticness: 0, energy: 0, valence: 0 },
  );
  return {
    acousticness: sum.acousticness / known.length,
    energy: sum.energy / known.length,
    valence: sum.valence / known.length,
  };
}

export function pointColor(
  features: AcousticCentroid | null | undefined,
  ownerCentroids: Array<AcousticCentroid | null>,
): Oklch {
  if (features) return acousticColor(features);
  const mean = meanCentroid(ownerCentroids);
  return mean ? acousticColor(mean) : GREY_NODE;
}

/** Neutral acoustics for a cluster-mode track whose features haven't landed. */
const NEUTRAL_ACOUSTICS: AcousticCentroid = {
  acousticness: 0.5,
  energy: 0.5,
  valence: 0.5,
};

export interface FieldPointColorInput {
  mode: PaletteMode;
  /** Per-track features, when the map payload ships them. */
  features: AcousticCentroid | null | undefined;
  /** Centroids of the playlists holding the track — the membership fallback. */
  owners: Array<AcousticCentroid | null>;
  /** Density cluster label (−1 = noise) — drives cluster-mode colour. */
  cluster: number;
  /** The library rank-equalizer. Null = raw acoustic colour. */
  equalizer: Equalizer | null;
  /** The cluster-keyed palette (cluster mode). */
  palette: ClusterPalette;
}

/**
 * The field's point colour with two palette modes:
 *  - `acoustic`: the track's own sound, rank-equalized across the library so
 *    the population fills the gamut instead of piling on red. Falls back to raw
 *    acoustic colour when no equalizer is built, and to the membership blend or
 *    grey state when the track has no features.
 *  - `cluster`: each density cluster gets a distinct base hue, shaded within
 *    the cluster by the track's own energy/valence.
 */
export function fieldPointColor(input: FieldPointColorInput): Oklch {
  const { mode, features, owners, cluster, equalizer, palette } = input;
  if (mode === "cluster") {
    if (cluster < 0) return GREY_NODE;
    const source = features ?? meanCentroid(owners) ?? NEUTRAL_ACOUSTICS;
    return palette.colorFor(cluster, source);
  }
  // acoustic mode
  const source = features ?? meanCentroid(owners);
  if (!source) return GREY_NODE;
  return equalizer ? equalizedColor(source, equalizer) : acousticColor(source);
}
