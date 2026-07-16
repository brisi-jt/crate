/**
 * Ambient-breath drift math (pure, no DOM / no d3 dependencies).
 *
 * The playlist graph and artist galaxy each keep their nodes gently drifting
 * at rest — "a drift visible at a glance, calm while reading" (graph spec §7).
 *
 * Prior attempts drove this through a d3 custom force that nudged node
 * *velocities* by a random amount each tick. That is a zero-mean random walk:
 * with the high velocity decay the simulation uses, the per-frame jitter
 * cancels out and the *net* displacement stays sub-pixel once the layout
 * settles — so the nodes look frozen even though the force is still firing.
 * It also rode d3's alpha lifecycle, which decays to zero (and which repeated
 * camera interaction drives into a deep local minimum a reheat can't escape),
 * so the motion died permanently after a burst of panning/zooming.
 *
 * This module instead computes an *absolute* drift offset per node from a
 * monotonic clock: two out-of-phase sinusoids around the node's rest position.
 * The caller pins each node (fx/fy) to `rest + offset` every frame, which
 * d3 honours verbatim (node.x = node.fx on every tick), so the drift is
 * immune to alpha decay, reheats, settle, and camera interaction. Net
 * displacement is bounded and guaranteed non-zero — perceptible by design.
 */

/** Peak drift offset from rest, in graph units, per axis. At the fitted zoom
 *  (≈1) this is also roughly the peak offset in screen pixels; the excursion
 *  is clearly visible at a glance but small relative to node spacing so it
 *  never looks like the layout is unstable. Each axis sums two sinusoids, so
 *  the true peak is up to amp×(1 + SECOND_TONE_RATIO). */
export const DRIFT_AMPLITUDE = 7;

/** Fraction of the amplitude carried by the faster second tone. A two-tone
 *  drift means the two axes are never simultaneously stationary, so every
 *  short observation window shows real travel — the single-sinusoid version
 *  had phase offsets where a 2 s window straddled a turning point and netted
 *  to nearly zero (a frozen-looking instant). */
export const SECOND_TONE_RATIO = 0.4;

/** Angular speeds (rad/ms). Base tones give ~4–7 s periods so a couple of
 *  seconds of watching shows clear travel; the second tones are faster and
 *  incommensurate, keeping the joint motion above zero and the path open
 *  (never a repeating orbit). */
export const DRIFT_OMEGA_X = 0.0015;
export const DRIFT_OMEGA_Y = 0.0009;
export const DRIFT_OMEGA_X2 = 0.0031;
export const DRIFT_OMEGA_Y2 = 0.0023;

/** Target drift frame rate. The RAF loop skips frames to roughly this cadence
 *  so the drift costs ~30 updates/s rather than one per animation frame. */
export const DRIFT_FPS = 30;
export const DRIFT_FRAME_MS = 1000 / DRIFT_FPS;

/**
 * A stable per-node phase offset derived from the node's id. Two nodes must
 * not drift in lock-step, so each gets a deterministic phase in [0, 2π) that
 * survives re-renders (no Math.random, so the phase is identical every mount).
 */
export function driftPhase(seed: string | number): number {
  const s = String(seed);
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  // Map the 32-bit hash to [0, 2π).
  return ((h >>> 0) / 0xffffffff) * Math.PI * 2;
}

/**
 * Absolute drift offset from rest for a node at time `tMs`.
 *
 * @param tMs   - monotonic time in ms (e.g. performance.now()).
 * @param phase - the node's stable phase from {@link driftPhase}.
 * @param amp   - peak offset (defaults to {@link DRIFT_AMPLITUDE}).
 */
export function driftOffset(
  tMs: number,
  phase: number,
  amp: number = DRIFT_AMPLITUDE,
): { dx: number; dy: number } {
  const s = amp * SECOND_TONE_RATIO;
  return {
    dx:
      amp * Math.sin(tMs * DRIFT_OMEGA_X + phase) +
      s * Math.sin(tMs * DRIFT_OMEGA_X2 + phase * 2.3),
    // cos on y with distinct phase terms keeps x and y out of step, so the
    // node moves on an open 2-D path rather than a diagonal line.
    dy:
      amp * Math.cos(tMs * DRIFT_OMEGA_Y + phase * 1.7) +
      s * Math.cos(tMs * DRIFT_OMEGA_Y2 + phase * 0.7),
  };
}

/**
 * Should the RAF loop run a drift update this frame? True at most once per
 * {@link DRIFT_FRAME_MS}. `last` is the timestamp of the previous update.
 */
export function shouldStepDrift(now: number, last: number): boolean {
  return now - last >= DRIFT_FRAME_MS;
}
