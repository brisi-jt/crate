/**
 * Map geometry shared by the canvas painter and the components that anchor
 * things to nodes (deck ghost placement, hover positioning). Formulas are
 * the graph rendering spec's §1/§3.
 */

/** Track count → node radius, sqrt scale, clamped 7–30 graph px. */
export function nodeRadius(trackCount: number): number {
  return Math.min(30, Math.max(7, 4 + 1.5 * Math.sqrt(trackCount)));
}

/** Shared-track count → overlap-edge width, 0.75–3 px. */
export function edgeWidth(shared: number): number {
  return 0.75 + 2.25 * Math.min(1, shared / 40);
}
