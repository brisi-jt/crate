/**
 * Track-field level of detail. The field grows toward 40k points; far out
 * it reads as an undifferentiated cloud. Below a zoom threshold, aggregate the
 * points into cluster blobs (hulls + a labelled disc per cluster); above it,
 * reveal the points. A transition band cross-fades the two so the drill-down is
 * continuous, not a hard swap.
 *
 * The decision is a pure function of zoom (`fieldLod`) so the painter stays
 * thin and the behaviour is unit-tested. `dominantCluster` also feeds the
 * cluster palette's neutral fallback for the genre-less mass.
 */

/** Below this zoom, points are fully hidden — only cluster blobs show. */
export const LOD_BLOB_ZOOM = 0.7;
/** Above this zoom, points are fully shown — blobs faded out. */
export const LOD_POINT_ZOOM = 1.5;

export interface FieldLod {
  showBlobs: boolean;
  showPoints: boolean;
  /** 0 at LOD_BLOB_ZOOM, 1 at LOD_POINT_ZOOM, linear across the band. */
  pointOpacity: number;
  /** 1 − pointOpacity — blobs recede as points arrive. */
  blobOpacity: number;
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

export function fieldLod(zoom: number): FieldLod {
  const span = LOD_POINT_ZOOM - LOD_BLOB_ZOOM;
  const pointOpacity = clamp01((zoom - LOD_BLOB_ZOOM) / span);
  const blobOpacity = 1 - pointOpacity;
  return {
    showBlobs: blobOpacity > 0,
    showPoints: pointOpacity > 0,
    pointOpacity,
    blobOpacity,
  };
}

export interface ClusterBlobPoint {
  x: number;
  y: number;
  cluster: number;
  fill: string;
}

export interface ClusterBlob {
  cluster: number;
  x: number;
  y: number;
  count: number;
  /** Aggregate disc radius, sqrt-scaled by member count. */
  radius: number;
  /** The cluster's representative fill (first member's colour). */
  fill: string;
}

const BLOB_MIN_RADIUS = 10;
const BLOB_SCALE = 3;

/**
 * Aggregate points into one blob per real cluster: centroid position, member
 * count, sqrt-scaled radius, representative colour. Noise (−1) is excluded.
 */
export function clusterBlobs(points: ClusterBlobPoint[]): ClusterBlob[] {
  const groups = new Map<
    number,
    { sx: number; sy: number; count: number; fill: string }
  >();
  for (const p of points) {
    if (p.cluster < 0) continue;
    const g = groups.get(p.cluster);
    if (g) {
      g.sx += p.x;
      g.sy += p.y;
      g.count++;
    } else {
      groups.set(p.cluster, { sx: p.x, sy: p.y, count: 1, fill: p.fill });
    }
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([cluster, g]) => ({
      cluster,
      x: g.sx / g.count,
      y: g.sy / g.count,
      count: g.count,
      radius: BLOB_MIN_RADIUS + BLOB_SCALE * Math.sqrt(g.count),
      fill: g.fill,
    }));
}

/**
 * The most populous real cluster (noise excluded), lowest id winning ties.
 * Null when there are no real clusters. In the owned library this is the
 * genre-less acoustically-central mass — the cluster palette tints it neutral.
 */
export function dominantCluster(clusters: number[]): number | null {
  const counts = new Map<number, number>();
  for (const c of clusters) {
    if (c < 0) continue;
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  if (counts.size === 0) return null;
  let best: number | null = null;
  let bestCount = -1;
  for (const [cluster, count] of counts) {
    if (
      count > bestCount ||
      (count === bestCount && best !== null && cluster < best)
    ) {
      best = cluster;
      bestCount = count;
    }
  }
  return best;
}
