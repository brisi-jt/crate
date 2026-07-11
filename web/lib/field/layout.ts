/**
 * Track-field geometry: UMAP coordinates → graph space, plus the cluster
 * hull outlines. Pure functions — the canvas renderer consumes the results.
 */

/** Constant point radius (graph rendering spec §10: scatter = fixed 3px). */
export const POINT_RADIUS = 3;

/** Graph-space span the wider UMAP axis is scaled to. */
export const FIELD_SPAN = 1400;

export interface XY {
  x: number;
  y: number;
}

/**
 * Scale raw UMAP coordinates into centered graph space: the wider axis spans
 * `span` graph px, aspect preserved, centroid of the extent at the origin.
 * Degenerate inputs (single point, zero extent) collapse to the origin.
 */
export function scalePositions(points: XY[], span: number = FIELD_SPAN): XY[] {
  if (points.length === 0) return [];
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  const extent = Math.max(maxX - minX, maxY - minY);
  if (extent === 0) return points.map(() => ({ x: 0, y: 0 }));
  const scale = span / extent;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return points.map((p) => ({
    x: (p.x - cx) * scale,
    y: (p.y - cy) * scale,
  }));
}

/**
 * Convex hull (Andrew monotone chain), counter-clockwise. Fewer than three
 * distinct points return the deduplicated input — the renderer strokes what
 * it gets with a wide round join, so segments and points still read as halos.
 */
export function convexHull(points: XY[]): XY[] {
  const sorted = [...points]
    .sort((a, b) => a.x - b.x || a.y - b.y)
    .filter(
      (p, i, arr) => i === 0 || p.x !== arr[i - 1].x || p.y !== arr[i - 1].y,
    );
  if (sorted.length <= 2) return sorted;

  const cross = (o: XY, a: XY, b: XY) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);

  const lower: XY[] = [];
  for (const p of sorted) {
    while (
      lower.length >= 2 &&
      cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0
    ) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper: XY[] = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i];
    while (
      upper.length >= 2 &&
      cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0
    ) {
      upper.pop();
    }
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return [...lower, ...upper];
}

export interface ClusterHull {
  cluster: number;
  hull: XY[];
}

/** Hull per density cluster (noise, cluster −1, never gets a hull). */
export function clusterHulls(
  points: Array<XY & { cluster: number }>,
): ClusterHull[] {
  const byCluster = new Map<number, XY[]>();
  for (const p of points) {
    if (p.cluster < 0) continue;
    const members = byCluster.get(p.cluster);
    if (members) members.push({ x: p.x, y: p.y });
    else byCluster.set(p.cluster, [{ x: p.x, y: p.y }]);
  }
  return [...byCluster.entries()]
    .sort(([a], [b]) => a - b)
    .map(([cluster, members]) => ({ cluster, hull: convexHull(members) }));
}
