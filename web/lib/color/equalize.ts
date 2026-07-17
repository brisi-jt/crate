/**
 * G4 — colour variety by rank-equalization.
 *
 * The acoustic colour formula (lib/color/acoustic.ts) is correct and binding;
 * the problem is its *inputs*. The library's driving features are centred
 * percentiles, so most tracks land at e≈0.5 → hue on red, and the map reads as
 * one red-magenta corner (measured: p50 hue 296°, 46% of tracks in 300–360°).
 *
 * The fix keeps the formula and spreads the *population*: replace each track's
 * raw driver with its RANK in the library, so colours are uniformly distributed
 * across the available gamut by construction. Rank is monotonic, so ordering is
 * preserved — a track redder than another stays redder, colour is still
 * evidence, just equalized. Cyan (100–260) stays empty; every legibility clamp
 * still holds because equalizedColor routes through acousticColor unchanged.
 *
 * Research: thoughts/shared/research/2026-07-17-graph-improvements-research.md §3.
 */

import type { AcousticCentroid, Oklch } from "./acoustic";
import { acousticColor, clampChroma, GREY_NODE } from "./acoustic";

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

/** The derived hue driver: organic 0 ←→ 1 electronic (design tokens §2). */
export function hueDriver(c: AcousticCentroid): number {
  return clamp01(0.8 * (1 - clamp01(c.acousticness)) + 0.2 * clamp01(c.energy));
}

/**
 * Map a population of values to an even 0..1 spread by rank. Ties share a rank
 * (order-independent). A single value maps to 0.5 (no spread possible).
 */
export function rankMap(values: number[]): number[] {
  const n = values.length;
  if (n === 0) return [];
  if (n === 1) return [0.5];
  const order = [...values.keys()].sort((a, b) => values[a] - values[b]);
  const out = new Array<number>(n);
  let i = 0;
  while (i < n) {
    // Group ties: all indices with the same value get the mean of their ranks.
    let j = i;
    while (j + 1 < n && values[order[j + 1]] === values[order[i]]) j++;
    const rank = (i + j) / 2 / (n - 1);
    for (let k = i; k <= j; k++) out[order[k]] = rank;
    i = j + 1;
  }
  return out;
}

/**
 * A sorted list of a library's driver values plus the query that turns any
 * value (seen or unseen) into its equalized rank in [0,1] by interpolation.
 */
interface RankCurve {
  /** Sorted unique-ish values (the empirical CDF x-axis). */
  sorted: number[];
  /** rankOf(v): position of v in the population, 0..1, clamped, interpolated. */
  rankOf: (value: number) => number;
}

function buildCurve(values: number[]): RankCurve {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  function rankOf(value: number): number {
    if (n === 0) return 0.5;
    if (n === 1) return 0.5;
    if (value <= sorted[0]) return 0;
    if (value >= sorted[n - 1]) return 1;
    // Binary search for the bracketing pair, then linear interpolate the rank.
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (sorted[mid] <= value) lo = mid;
      else hi = mid;
    }
    const span = sorted[hi] - sorted[lo] || 1;
    const frac = (value - sorted[lo]) / span;
    return (lo + frac) / (n - 1);
  }
  return { sorted, rankOf };
}

/**
 * The equalizing transform built once per library. Carries the empirical rank
 * curves for the three colour drivers (hue, chroma, lightness).
 */
export interface Equalizer {
  hueRankOf: (e: number) => number;
  energyRankOf: (energy: number) => number;
  valenceRankOf: (valence: number) => number;
  /** Convenience: the equalized hue driver for a centroid. */
  hueDriver: (c: AcousticCentroid) => number;
}

/** Build the equalizer from every enriched centroid in the library. */
export function rankEqualize(library: AcousticCentroid[]): Equalizer {
  const hue = buildCurve(library.map(hueDriver));
  const energy = buildCurve(library.map((c) => clamp01(c.energy)));
  const valence = buildCurve(library.map((c) => clamp01(c.valence)));
  return {
    hueRankOf: hue.rankOf,
    energyRankOf: energy.rankOf,
    valenceRankOf: valence.rankOf,
    hueDriver: (c) => hue.rankOf(hueDriver(c)),
  };
}

/**
 * Colour a centroid through the equalized drivers. Same OKLCH mapping as
 * acousticColor — hue arc, chroma-from-energy, lightness-from-valence,
 * cyan-ban, extreme-taper — but each driver is its library rank, so the
 * population fills the gamut evenly instead of bunching on red.
 */
export function equalizedColor(
  centroid: AcousticCentroid,
  eq: Equalizer,
): Oklch {
  const e = eq.hueRankOf(hueDriver(centroid));
  const energyRank = eq.energyRankOf(clamp01(centroid.energy));
  const valenceRank = eq.valenceRankOf(clamp01(centroid.valence));
  // Re-derive an acousticness that reproduces this equalized e with the same
  // formula, so acousticColor stays the single source of the OKLCH mapping.
  // e = 0.8·(1−a) + 0.2·energyRank  ⇒  a = 1 − (e − 0.2·energyRank) / 0.8
  const a = clamp01(1 - (e - 0.2 * energyRank) / 0.8);
  return acousticColor({
    acousticness: a,
    energy: energyRank,
    valence: valenceRank,
  });
}

// --------------------------------------------------------- cluster palette

const NEUTRAL_CHROMA = 0.035;
/** Golden-angle hue stepping gives maximal separation for any cluster count. */
const GOLDEN_ANGLE = 137.508;
/** Anchor so cluster hues avoid the empty cyan band where possible. */
const HUE_ANCHOR = 40;

/**
 * Cluster-keyed palette (G4 optional mode): each cluster gets a distinct base
 * hue; lightness/chroma vary within the cluster from the track's own acoustics.
 * The dominant genre-less cluster (per the 4a clustering handoff — ~43% of the
 * library has no genre and shares one acoustically-central cluster) gets a
 * neutral tint so it reads as "mixed / uncategorised", not a false identity.
 * Noise (−1) is the grey out-of-gamut state.
 */
export interface ClusterPalette {
  baseHue: (cluster: number) => number;
  isNeutral: (cluster: number) => boolean;
  colorFor: (cluster: number, centroid: AcousticCentroid) => Oklch;
}

export function clusterPalette(
  clusters: number[],
  noiseCluster = -1,
  neutralCluster: number | null = null,
): ClusterPalette {
  const real = [...new Set(clusters)]
    .filter((c) => c !== noiseCluster)
    .sort((a, b) => a - b);
  const hueByCluster = new Map<number, number>();
  real.forEach((c, i) => {
    hueByCluster.set(c, (((HUE_ANCHOR + i * GOLDEN_ANGLE) % 360) + 360) % 360);
  });

  function baseHue(cluster: number): number {
    return hueByCluster.get(cluster) ?? HUE_ANCHOR;
  }

  function isNeutral(cluster: number): boolean {
    return cluster === neutralCluster;
  }

  function colorFor(cluster: number, centroid: AcousticCentroid): Oklch {
    if (cluster === noiseCluster) return GREY_NODE;
    const energy = clamp01(centroid.energy);
    const valence = clamp01(centroid.valence);
    const l = 0.48 + 0.27 * valence;
    if (isNeutral(cluster)) {
      // Muted: a barely-tinted neutral, still varying on lightness by valence.
      return { l, c: clampChroma(NEUTRAL_CHROMA, l), h: baseHue(cluster) };
    }
    const c0 = 0.05 + 0.13 * energy;
    return { l, c: clampChroma(c0, l), h: baseHue(cluster) };
  }

  return { baseHue, isNeutral, colorFor };
}
