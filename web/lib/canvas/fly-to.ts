/**
 * Search-to-focus fly-to targets.
 *
 * ⌘K search (or any "jump to X") dispatches a fly-to target: which canvas mode
 * it belongs to, the node id, and a monotonic nonce. Each canvas consumes only
 * the target for its own mode and fires the camera glide once per nonce, so
 * searching the same node twice re-fires. Pure so the fire-once / re-fire /
 * ignore-other-mode logic is unit-tested; the camera call lives in the canvas.
 */

import type { MapMode } from "@/lib/store/ui";

/** A node id is a number on playlist/track maps, a string key on the galaxy. */
export type FlyId = number | string;

export interface FlyTarget {
  mode: MapMode;
  id: FlyId;
  nonce: number;
}

/** Bump a new fly-to target, keeping the nonce strictly increasing. */
export function bumpFlyTo(
  previous: FlyTarget | null,
  next: { mode: MapMode; id: FlyId },
): FlyTarget {
  return { mode: next.mode, id: next.id, nonce: (previous?.nonce ?? 0) + 1 };
}

/** The target for this canvas's mode, or null if it belongs to another mode. */
export function flyToForMode(
  target: FlyTarget | null,
  mode: MapMode,
): FlyTarget | null {
  if (!target || target.mode !== mode) return null;
  return target;
}

/** Whether a canvas should fire the glide: a target exists with a fresh nonce. */
export function shouldFireFlyTo(
  target: { nonce: number } | null,
  lastFiredNonce: number,
): boolean {
  return target !== null && target.nonce > lastFiredNonce;
}
