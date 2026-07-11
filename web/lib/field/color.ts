/**
 * Track-field point color — the acoustic mapping, fed from the best source
 * available (color is evidence, one formula everywhere):
 *
 * 1. Per-track feature percentiles, when the map payload ships them.
 * 2. Otherwise the mean centroid of the playlists holding the track — the
 *    Phase 9 "playlist-colored" scatter. Single-membership tracks land on
 *    exactly their playlist's color; multi-membership tracks blend in
 *    centroid space (never in color space) before mapping.
 * 3. No membership or no enriched owner → the grey out-of-gamut state.
 */

import type { AcousticCentroid } from "@/lib/color/acoustic";
import { acousticColor, GREY_NODE, type Oklch } from "@/lib/color/acoustic";

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
