/**
 * The acoustic color mapping — color = data, everywhere.
 *
 * One function turns a playlist/track's acoustic centroid into its OKLCH
 * color: hue tracks organic↔electronic, chroma tracks energy, lightness
 * tracks valence. Similar sound ⇒ similar color, consistently.
 *
 * Formula source (binding): thoughts/shared/mockups/2026-07-11-design-tokens.md §2.
 * Inputs are LIBRARY PERCENTILES (0–1), never raw feature values.
 */

export interface AcousticCentroid {
  /** P(acousticness) */
  acousticness: number;
  /** P(0.6·energy + 0.4·danceability) — the energy composite */
  energy: number;
  /** P(valence) */
  valence: number;
}

export interface Oklch {
  l: number;
  c: number;
  h: number;
}

const CHROMA_MAX = 0.18;

/**
 * Grey out-of-gamut state for entities with no features yet. Sits below both
 * the lightness floor (0.48) and chroma floor (0.05) of the data ramp, so
 * "unknown" can never be mistaken for "calm".
 */
export const GREY_NODE: Oklch = { l: 0.42, c: 0.012, h: 265 };

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

export function acousticColor(centroid: AcousticCentroid): Oklch {
  const a = clamp01(centroid.acousticness);
  const energy = clamp01(centroid.energy);
  const v = clamp01(centroid.valence);

  // organic 0 ←→ 1 electronic; acousticness drives, energy nudges hybrids
  const e = clamp01(0.8 * (1 - a) + 0.2 * energy);

  // Hue arc 80 → 280 via red/magenta — never enters cyan (100–260 unused)
  const h = (((80 - 160 * e) % 360) + 360) % 360;

  const c0 = 0.05 + 0.13 * energy;
  const l = 0.48 + 0.27 * v;

  return { l, c: clampChroma(c0, l), h };
}

/**
 * Chroma taper at the lightness extremes: high chroma near either end goes
 * garish and loses legibility against the canvas.
 */
export function clampChroma(chroma: number, l: number): number {
  const cHi = l > 0.68 ? CHROMA_MAX - 0.45 * (l - 0.68) : CHROMA_MAX;
  const cLo = l < 0.52 ? CHROMA_MAX - 0.6 * (0.52 - l) : CHROMA_MAX;
  return Math.min(chroma, cHi, cLo);
}

/** CSS color string (canvas 2D fillStyle accepts oklch() in modern engines). */
export function oklchString({ l, c, h }: Oklch): string {
  return `oklch(${round(l, 4)} ${round(c, 4)} ${round(h, 2)})`;
}

/**
 * Parse an `oklch(l c h)` string back to its components — the inverse of
 * oklchString, for surfaces that carry the fill as a string (render points)
 * but need the numeric colour again (hover-card tint). Falls back to the grey
 * state on anything unparseable.
 */
export function parseOklch(value: string): Oklch {
  const match = value.match(/oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/i);
  if (!match) return GREY_NODE;
  return {
    l: Number.parseFloat(match[1]),
    c: Number.parseFloat(match[2]),
    h: Number.parseFloat(match[3]),
  };
}

/**
 * Selection-ring color: the node's own color lifted by +0.12 lightness with
 * the chroma clamp re-applied at the new lightness (graph spec §1).
 */
export function selectionRing(color: Oklch): Oklch {
  const l = Math.min(color.l + 0.12, 0.97);
  return { l, c: clampChroma(color.c, l), h: color.h };
}

function round(x: number, places: number): number {
  const factor = 10 ** places;
  return Math.round(x * factor) / factor;
}
