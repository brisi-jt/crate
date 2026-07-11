import { describe, expect, it } from "vitest";
import { clusterHulls, convexHull, scalePositions } from "./layout";

describe("scalePositions", () => {
  it("scales the wider axis to the span, centered on the origin", () => {
    // x extent 10 (wider), y extent 5 — scale = span / 10.
    const scaled = scalePositions(
      [
        { x: 0, y: 0 },
        { x: 10, y: 5 },
      ],
      1000,
    );
    expect(scaled[0]).toEqual({ x: -500, y: -250 });
    expect(scaled[1]).toEqual({ x: 500, y: 250 });
  });

  it("preserves aspect ratio (no per-axis stretch)", () => {
    const scaled = scalePositions(
      [
        { x: 0, y: 0 },
        { x: 4, y: 2 },
        { x: 2, y: 1 },
      ],
      400,
    );
    // Midpoint stays the midpoint; y spans half of x's span.
    expect(scaled[2]).toEqual({ x: 0, y: 0 });
    expect(scaled[1].y - scaled[0].y).toBeCloseTo(200);
    expect(scaled[1].x - scaled[0].x).toBeCloseTo(400);
  });

  it("collapses degenerate extents to the origin", () => {
    expect(scalePositions([{ x: 3, y: 7 }])).toEqual([{ x: 0, y: 0 }]);
    expect(scalePositions([])).toEqual([]);
  });
});

describe("convexHull", () => {
  it("drops interior points of a square", () => {
    const hull = convexHull([
      { x: 0, y: 0 },
      { x: 4, y: 0 },
      { x: 4, y: 4 },
      { x: 0, y: 4 },
      { x: 2, y: 2 },
    ]);
    expect(hull).toHaveLength(4);
    expect(hull).toEqual(
      expect.arrayContaining([
        { x: 0, y: 0 },
        { x: 4, y: 0 },
        { x: 4, y: 4 },
        { x: 0, y: 4 },
      ]),
    );
  });

  it("drops collinear midpoints", () => {
    const hull = convexHull([
      { x: 0, y: 0 },
      { x: 2, y: 0 },
      { x: 4, y: 0 },
      { x: 2, y: 3 },
    ]);
    expect(hull).toHaveLength(3);
  });

  it("returns deduplicated input below three distinct points", () => {
    expect(
      convexHull([
        { x: 1, y: 1 },
        { x: 1, y: 1 },
      ]),
    ).toEqual([{ x: 1, y: 1 }]);
  });
});

describe("clusterHulls", () => {
  it("builds one hull per cluster and skips noise", () => {
    const hulls = clusterHulls([
      { x: 0, y: 0, cluster: 0 },
      { x: 1, y: 0, cluster: 0 },
      { x: 0, y: 1, cluster: 0 },
      { x: 10, y: 10, cluster: 1 },
      { x: 99, y: 99, cluster: -1 },
    ]);
    expect(hulls.map((h) => h.cluster)).toEqual([0, 1]);
    expect(hulls[0].hull).toHaveLength(3);
    expect(hulls[1].hull).toEqual([{ x: 10, y: 10 }]);
  });
});
