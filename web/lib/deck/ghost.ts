/**
 * Ghost-node placement: where the auditioning candidate hovers relative to
 * its target playlist node.
 *
 * The map's force layout has no acoustic axes, so the ghost's *offset from
 * the target* encodes the acoustic relationship instead: the x direction is
 * the organic<->electronic axis (more acoustic drifts right), the y direction
 * is energy (less energetic sinks down — screen y grows downward). A
 * candidate that sounds exactly like the playlist floats close; a mismatch
 * pushes further out, capped so the ghost always stays in the target's
 * neighborhood.
 */

export interface AcousticPoint {
  /** Library percentiles, 0..1. */
  energy: number;
  valence: number;
  acousticness: number;
}

export interface GhostOffset {
  dx: number;
  dy: number;
}

/** Gap between the target's rim and a perfectly matching ghost, in graph px. */
export const GHOST_BASE_GAP = 24;

/** Extra distance a maximal acoustic mismatch adds, in graph px. */
export const GHOST_SPREAD = 60;

/** Resting direction when candidate and playlist sound identical: up-left,
 * mirroring the deck mockup's composition. */
const NEUTRAL_ANGLE = (-3 * Math.PI) / 4;

/** The canvas background (globals.css --canvas) as numbers, for pre-mixing. */
const CANVAS_OKLCH = { l: 0.13, c: 0.015, h: 265 };

/**
 * Ghost fill: the candidate's color pre-mixed 25% toward the canvas — a
 * solid value (not alpha), per the rendering spec, so overlapping edges
 * never show through the ghost's body. Hue stays the candidate's own.
 */
export function ghostFill(color: { l: number; c: number; h: number }): {
  l: number;
  c: number;
  h: number;
} {
  return {
    l: CANVAS_OKLCH.l + 0.25 * (color.l - CANVAS_OKLCH.l),
    c: CANVAS_OKLCH.c + 0.25 * (color.c - CANVAS_OKLCH.c),
    h: color.h,
  };
}

export function ghostOffset(
  candidate: AcousticPoint,
  playlist: AcousticPoint,
  targetRadius: number,
): GhostOffset {
  const x = candidate.acousticness - playlist.acousticness;
  const y = playlist.energy - candidate.energy; // energy drop sinks the ghost
  const norm = Math.hypot(x, y);
  const distance =
    targetRadius + GHOST_BASE_GAP + GHOST_SPREAD * Math.min(1, norm);
  if (norm < 1e-6) {
    return {
      dx: Math.cos(NEUTRAL_ANGLE) * distance,
      dy: Math.sin(NEUTRAL_ANGLE) * distance,
    };
  }
  return { dx: (x / norm) * distance, dy: (y / norm) * distance };
}
