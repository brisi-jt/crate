import { describe, expect, it } from "vitest";
import { minimapLayout, viewportRect } from "./minimap";

/**
 * G7 — corner mini-map. Projects the field's graph-space extent into a small
 * fixed box and marks where the camera viewport sits, so a 5,862-point (→40k)
 * field is orientable. Pure geometry, unit-tested; the canvas draws the result.
 */

describe("minimapLayout", () => {
  const points = [
    { x: -100, y: -50 },
    { x: 100, y: 50 },
    { x: 0, y: 0 },
  ];

  it("fits the wider axis to the box, preserving aspect", () => {
    const layout = minimapLayout(points, { width: 120, height: 80 });
    // extent is 200 wide × 100 tall → wider axis (x) fills 120 px.
    expect(layout.scale).toBeCloseTo(120 / 200, 6);
  });

  it("projects a point into box coordinates centred in the box", () => {
    const layout = minimapLayout(points, { width: 120, height: 80 });
    const centre = layout.project(0, 0);
    // origin is the extent centre → box centre
    expect(centre.x).toBeCloseTo(60, 6);
    expect(centre.y).toBeCloseTo(40, 6);
  });

  it("keeps corners inside the box", () => {
    const layout = minimapLayout(points, { width: 120, height: 80 });
    for (const p of points) {
      const q = layout.project(p.x, p.y);
      expect(q.x).toBeGreaterThanOrEqual(0);
      expect(q.x).toBeLessThanOrEqual(120);
      expect(q.y).toBeGreaterThanOrEqual(0);
      expect(q.y).toBeLessThanOrEqual(80);
    }
  });

  it("handles an empty field without dividing by zero", () => {
    const layout = minimapLayout([], { width: 120, height: 80 });
    const q = layout.project(0, 0);
    expect(Number.isFinite(q.x)).toBe(true);
    expect(Number.isFinite(q.y)).toBe(true);
  });
});

describe("viewportRect", () => {
  const points = [
    { x: -100, y: -50 },
    { x: 100, y: 50 },
  ];

  it("marks the visible camera window as a rect inside the mini-map", () => {
    const layout = minimapLayout(points, { width: 120, height: 80 });
    // camera shows graph-space [-50..50] × [-25..25] → a quarter-ish rect.
    const rect = viewportRect(layout, {
      minX: -50,
      minY: -25,
      maxX: 50,
      maxY: 25,
    });
    // width = 100 graph px * scale (0.6) = 60
    expect(rect.width).toBeCloseTo(100 * layout.scale, 6);
    expect(rect.height).toBeCloseTo(50 * layout.scale, 6);
    // centred in the box
    expect(rect.x + rect.width / 2).toBeCloseTo(60, 4);
    expect(rect.y + rect.height / 2).toBeCloseTo(40, 4);
  });

  it("clamps a viewport larger than the field to the box", () => {
    const layout = minimapLayout(points, { width: 120, height: 80 });
    const rect = viewportRect(layout, {
      minX: -1000,
      minY: -1000,
      maxX: 1000,
      maxY: 1000,
    });
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.y).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width).toBeLessThanOrEqual(120 + 1e-6);
    expect(rect.y + rect.height).toBeLessThanOrEqual(80 + 1e-6);
  });
});
