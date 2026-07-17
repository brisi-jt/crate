/**
 * Client-side pin sampler — the variety layer for insight pins.
 *
 * The backend hands us a wide, family-tagged candidate pool
 * (GET /v1/insights/pins/candidates); the pins on screen are a small, rotating
 * sample of it. Rotation is seeded per session so a refresh brings fresh pins,
 * but the same seed is perfectly reproducible (no flicker on re-render). The
 * sample obeys three rules:
 *
 *  1. category quota — at most one pin per family per refresh, so the surface
 *     never shows three variations of the same idea;
 *  2. elitist weighting — a candidate's chance scales with salience^k, so the
 *     strongest readings surface most, without ever being the only ones;
 *  3. anti-repeat — candidates shown in recent sessions are down-weighted, so
 *     rotation actually rotates.
 *
 * Dismissed candidates are removed outright. Pure, deterministic, unit-tested —
 * components just render the result.
 */

/** One candidate from GET /v1/insights/pins/candidates. */
export interface PinCandidate {
  family: string;
  category: string;
  metric_ref: string;
  anchor: string;
  line: string;
  dismissible_id: string;
  salience: number;
}

export interface SampleArgs {
  candidates: PinCandidate[];
  /** Per-session seed. Same seed → same sample. */
  seed: number;
  /** Dismissed `dismissible_id`s — removed from the pool entirely. */
  dismissed?: ReadonlySet<string>;
  /**
   * Recently-shown history: `dismissible_id` → number of recent sessions it was
   * shown in. Higher = more down-weighted. Absent = never recently shown.
   */
  shownHistory?: Readonly<Record<string, number>>;
  /** How many pins to surface at once. */
  maxVisible?: number;
  /** Salience exponent — higher makes selection more elitist. */
  salienceExponent?: number;
}

/**
 * Mulberry32 — a tiny, fast, well-distributed seeded PRNG. Deterministic for a
 * given 32-bit seed; returns a float in [0, 1).
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const DEFAULT_MAX_VISIBLE = 3;
const DEFAULT_SALIENCE_EXPONENT = 2;
/** Each recent-session appearance multiplies weight by this (down-weight). */
const RECENCY_DECAY = 0.45;

/** Weight for one candidate: salience^k, decayed by recent appearances. */
function candidateWeight(
  candidate: PinCandidate,
  exponent: number,
  shownHistory: Readonly<Record<string, number>>,
): number {
  // Clamp salience into [0, 1]; floor keeps a weak-but-fresh pin selectable.
  const s = Math.min(1, Math.max(0, candidate.salience));
  const base = s ** exponent + 0.001;
  const shown = shownHistory[candidate.dismissible_id] ?? 0;
  return base * RECENCY_DECAY ** shown;
}

/**
 * Draw one candidate from a weighted list using the supplied uniform [0,1)
 * draw. Returns the index, or -1 if the list is empty / all weights are zero.
 */
function weightedPick(weights: number[], draw: number): number {
  const total = weights.reduce((sum, w) => sum + w, 0);
  if (total <= 0) return weights.length > 0 ? 0 : -1;
  let target = draw * total;
  for (let i = 0; i < weights.length; i++) {
    target -= weights[i];
    if (target < 0) return i;
  }
  return weights.length - 1;
}

/**
 * Sample the pins to show. Deterministic in `seed`. Respects dismissals, the
 * one-per-family quota, elitist salience weighting, and recent-shown decay.
 */
export function samplePins(args: SampleArgs): PinCandidate[] {
  const {
    candidates,
    seed,
    dismissed = new Set<string>(),
    shownHistory = {},
    maxVisible = DEFAULT_MAX_VISIBLE,
    salienceExponent = DEFAULT_SALIENCE_EXPONENT,
  } = args;

  // Drop dismissed candidates outright.
  const pool = candidates.filter((c) => !dismissed.has(c.dismissible_id));
  if (pool.length === 0) return [];

  const rng = mulberry32(seed);
  const chosen: PinCandidate[] = [];
  const usedFamilies = new Set<string>();
  // Work on a mutable copy so drawing removes without touching the input.
  let remaining = pool.slice();

  while (chosen.length < maxVisible && remaining.length > 0) {
    const weights = remaining.map((c) =>
      candidateWeight(c, salienceExponent, shownHistory),
    );
    const idx = weightedPick(weights, rng());
    if (idx < 0) break;
    const pick = remaining[idx];
    chosen.push(pick);
    usedFamilies.add(pick.family);
    // Enforce the quota: drop the pick AND every other candidate of its family.
    remaining = remaining.filter((c) => !usedFamilies.has(c.family));
  }

  return chosen;
}
