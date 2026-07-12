import { describe, expect, it } from "vitest";
import type { FingerprintAxis } from "@/lib/api/schemas";
import {
  FINGERPRINT_ORDER,
  fingerprintSpokes,
  polar,
  polygonPoints,
} from "./fingerprint";

function axes(): FingerprintAxis[] {
  return FINGERPRINT_ORDER.map((feature, i) => ({
    feature,
    percentile: (i + 1) / 10,
  }));
}

describe("polar", () => {
  it("places angle 0 straight up (12 o'clock)", () => {
    const p = polar(100, 100, 50, 0);
    expect(p.x).toBeCloseTo(100, 5);
    expect(p.y).toBeCloseTo(50, 5);
  });

  it("goes clockwise: quarter turn is to the right", () => {
    const p = polar(100, 100, 50, Math.PI / 2);
    expect(p.x).toBeCloseTo(150, 5);
    expect(p.y).toBeCloseTo(100, 5);
  });
});

describe("fingerprintSpokes", () => {
  it("returns one spoke per present feature in canonical order", () => {
    const spokes = fingerprintSpokes(axes(), 100, 100, 80);
    expect(spokes).toHaveLength(9);
    expect(spokes.map((s) => s.feature)).toEqual([...FINGERPRINT_ORDER]);
  });

  it("distributes spokes evenly around the circle", () => {
    const spokes = fingerprintSpokes(axes(), 0, 0, 80);
    expect(spokes[0].angle).toBeCloseTo(0);
    expect(spokes[1].angle).toBeCloseTo((2 * Math.PI) / 9);
    expect(spokes[8].angle).toBeCloseTo((2 * Math.PI * 8) / 9);
  });

  it("scales the tick radius by percentile", () => {
    const spokes = fingerprintSpokes(
      [{ feature: "energy", percentile: 0.5 }],
      0,
      0,
      80,
    );
    // single spoke at angle 0 → straight up, radius 80*0.5 = 40
    expect(spokes[0].point.y).toBeCloseTo(-40);
    expect(spokes[0].outer.y).toBeCloseTo(-80);
  });

  it("clamps a zero percentile to a visible stub, never the center", () => {
    const spokes = fingerprintSpokes(
      [{ feature: "energy", percentile: 0 }],
      0,
      0,
      80,
    );
    const r = Math.hypot(spokes[0].point.x, spokes[0].point.y);
    expect(r).toBeGreaterThan(0);
    expect(r).toBeCloseTo(80 * 0.02, 3);
  });

  it("returns an empty array before enrichment", () => {
    expect(fingerprintSpokes([], 0, 0, 80)).toEqual([]);
  });

  it("drops unknown features and re-spaces the remainder", () => {
    const spokes = fingerprintSpokes(
      [
        { feature: "energy", percentile: 0.5 },
        { feature: "valence", percentile: 0.5 },
      ],
      0,
      0,
      80,
    );
    expect(spokes).toHaveLength(2);
    expect(spokes[1].angle).toBeCloseTo(Math.PI);
  });
});

describe("polygonPoints", () => {
  it("emits one x,y pair per spoke", () => {
    const spokes = fingerprintSpokes(axes(), 100, 100, 80);
    const pts = polygonPoints(spokes).split(" ");
    expect(pts).toHaveLength(9);
    expect(pts[0]).toMatch(/^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/);
  });
});
