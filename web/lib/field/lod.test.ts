import { describe, expect, it } from "vitest";
import {
  clusterBlobs,
  dominantCluster,
  fieldLod,
  LOD_BLOB_ZOOM,
  LOD_POINT_ZOOM,
} from "./lod";

/**
 * G7 — zoom level-of-detail for the track field. Far out, 5,862 points read as
 * a cloud; aggregate them into cluster blobs. Near in, reveal the points. The
 * decision is a pure function of zoom so it's testable and the painter stays
 * thin. `dominantCluster` also feeds the G4 neutral-fallback for the genre-less
 * mass.
 */

describe("fieldLod", () => {
  it("shows cluster blobs (not points) when zoomed far out", () => {
    const lod = fieldLod(LOD_BLOB_ZOOM - 0.1);
    expect(lod.showBlobs).toBe(true);
    expect(lod.showPoints).toBe(false);
  });

  it("shows points (not blobs) when zoomed in", () => {
    const lod = fieldLod(LOD_POINT_ZOOM + 0.1);
    expect(lod.showBlobs).toBe(false);
    expect(lod.showPoints).toBe(true);
  });

  it("cross-fades in the transition band (both visible, opacities sum sanely)", () => {
    const mid = (LOD_BLOB_ZOOM + LOD_POINT_ZOOM) / 2;
    const lod = fieldLod(mid);
    expect(lod.showBlobs).toBe(true);
    expect(lod.showPoints).toBe(true);
    expect(lod.pointOpacity).toBeGreaterThan(0);
    expect(lod.pointOpacity).toBeLessThan(1);
    expect(lod.blobOpacity).toBeGreaterThan(0);
    expect(lod.blobOpacity).toBeLessThan(1);
  });

  it("point opacity rises monotonically with zoom across the band", () => {
    const lo = fieldLod(LOD_BLOB_ZOOM).pointOpacity;
    const mid = fieldLod((LOD_BLOB_ZOOM + LOD_POINT_ZOOM) / 2).pointOpacity;
    const hi = fieldLod(LOD_POINT_ZOOM).pointOpacity;
    expect(mid).toBeGreaterThanOrEqual(lo);
    expect(hi).toBeGreaterThanOrEqual(mid);
    expect(hi).toBeCloseTo(1, 6);
    expect(lo).toBeCloseTo(0, 6);
  });

  it("blob opacity is the inverse of point opacity", () => {
    for (const z of [0.5, 1, 1.5, 2, 3]) {
      const lod = fieldLod(z);
      expect(lod.blobOpacity).toBeCloseTo(1 - lod.pointOpacity, 6);
    }
  });
});

describe("clusterBlobs", () => {
  const points = [
    { x: 0, y: 0, cluster: 0, fill: "oklch(0.6 0.1 40)" },
    { x: 10, y: 0, cluster: 0, fill: "oklch(0.6 0.1 40)" },
    { x: 0, y: 10, cluster: 0, fill: "oklch(0.6 0.1 40)" },
    { x: 100, y: 100, cluster: 1, fill: "oklch(0.5 0.1 200)" },
    { x: 110, y: 100, cluster: 1, fill: "oklch(0.5 0.1 200)" },
    { x: 500, y: 500, cluster: -1, fill: "oklch(0.42 0.01 265)" },
  ];

  it("aggregates one blob per real cluster (noise excluded)", () => {
    const blobs = clusterBlobs(points);
    expect(blobs.map((b) => b.cluster).sort()).toEqual([0, 1]);
  });

  it("centres each blob on its members' centroid", () => {
    const blobs = clusterBlobs(points);
    const c0 = blobs.find((b) => b.cluster === 0);
    expect(c0?.x).toBeCloseTo((0 + 10 + 0) / 3, 6);
    expect(c0?.y).toBeCloseTo((0 + 0 + 10) / 3, 6);
  });

  it("sizes each blob by member count (radius grows with sqrt)", () => {
    const many = [
      ...Array.from({ length: 100 }, (_, i) => ({
        x: i,
        y: 0,
        cluster: 0,
        fill: "x",
      })),
      { x: 0, y: 0, cluster: 1, fill: "y" },
      { x: 1, y: 0, cluster: 1, fill: "y" },
    ];
    const blobs = clusterBlobs(many);
    const big = blobs.find((b) => b.cluster === 0);
    const small = blobs.find((b) => b.cluster === 1);
    expect(big?.count).toBe(100);
    expect(small?.count).toBe(2);
    expect((big?.radius ?? 0) > (small?.radius ?? 0)).toBe(true);
  });

  it("returns an empty list when there are no clustered points", () => {
    expect(clusterBlobs([{ x: 0, y: 0, cluster: -1, fill: "g" }])).toEqual([]);
  });
});

describe("dominantCluster", () => {
  it("returns the most populous real cluster", () => {
    expect(dominantCluster([0, 0, 0, 1, 1, 2, -1, -1, -1, -1])).toBe(0);
  });

  it("ignores noise even when noise is the largest group", () => {
    expect(dominantCluster([-1, -1, -1, -1, 0, 0, 1])).toBe(0);
  });

  it("returns null with no real clusters", () => {
    expect(dominantCluster([-1, -1])).toBeNull();
    expect(dominantCluster([])).toBeNull();
  });

  it("is deterministic on ties (lowest cluster id wins)", () => {
    expect(dominantCluster([2, 2, 1, 1])).toBe(1);
  });
});
