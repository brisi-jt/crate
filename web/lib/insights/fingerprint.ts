/**
 * Acoustic-fingerprint radial geometry — the page's signature object.
 *
 * Nine spokes at fixed angles (energy at 12 o'clock, clockwise), each a tick
 * at its library-percentile radius. The enclosed polygon is filled with the
 * library's centroid color. Pure math so the geometry is unit-tested.
 */

import type { FingerprintAxis } from "@/lib/api/schemas";

/** Stable spoke order — matches the API's fingerprint feature order. */
export const FINGERPRINT_ORDER = [
  "energy",
  "valence",
  "danceability",
  "acousticness",
  "instrumentalness",
  "liveness",
  "speechiness",
  "tempo",
  "loudness",
] as const;

export interface FingerprintSpoke {
  feature: string;
  percentile: number;
  /** Angle in radians, 0 = up (12 o'clock), clockwise. */
  angle: number;
  /** Tick endpoint at the percentile radius. */
  point: { x: number; y: number };
  /** Outer endpoint at the ring (percentile = 1). */
  outer: { x: number; y: number };
  /** Short axis label for the ring. */
  label: string;
}

const LABELS: Record<string, string> = {
  energy: "ENE",
  valence: "VAL",
  danceability: "DNC",
  acousticness: "ACO",
  instrumentalness: "INS",
  liveness: "LIV",
  speechiness: "SPE",
  tempo: "TMP",
  loudness: "LOU",
};

/** Point on a circle of `radius` at `angle` (0 = up, clockwise), origin `cx,cy`. */
export function polar(
  cx: number,
  cy: number,
  radius: number,
  angle: number,
): { x: number; y: number } {
  return {
    x: cx + radius * Math.sin(angle),
    y: cy - radius * Math.cos(angle),
  };
}

/**
 * Resolve the fingerprint axes into positioned spokes. Missing features are
 * dropped (the API ships all nine once enriched; an empty array before then).
 * Percentiles clamp to [0.02, 1] so a zero axis still shows a stub, never a
 * degenerate polygon collapsed to the center.
 */
export function fingerprintSpokes(
  fingerprint: FingerprintAxis[],
  cx: number,
  cy: number,
  radius: number,
): FingerprintSpoke[] {
  const byFeature = new Map(fingerprint.map((f) => [f.feature, f.percentile]));
  const present = FINGERPRINT_ORDER.filter((f) => byFeature.has(f));
  const n = present.length;
  if (n === 0) return [];

  return present.map((feature, i) => {
    const angle = (2 * Math.PI * i) / n;
    const raw = byFeature.get(feature) ?? 0;
    const p = Math.min(1, Math.max(0.02, raw));
    return {
      feature,
      percentile: raw,
      angle,
      point: polar(cx, cy, radius * p, angle),
      outer: polar(cx, cy, radius, angle),
      label: LABELS[feature] ?? feature.slice(0, 3).toUpperCase(),
    };
  });
}

/** SVG polygon `points` string from the spoke tick endpoints. */
export function polygonPoints(spokes: FingerprintSpoke[]): string {
  return spokes.map((s) => `${round(s.point.x)},${round(s.point.y)}`).join(" ");
}

function round(x: number): number {
  return Math.round(x * 100) / 100;
}
