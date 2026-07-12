import { describe, expect, it } from "vitest";
import type { AddsOverTime } from "@/lib/api/schemas";
import { GREY_NODE } from "@/lib/color/acoustic";
import { axisTickIndices, coreBands, formatCoreMonth } from "./core-sample";

describe("coreBands", () => {
  it("tints each month from its centroid", () => {
    const adds: AddsOverTime[] = [
      {
        month: "2024-01",
        count: 10,
        centroid: { acousticness: 0.9, energy: 0.2, valence: 0.5 },
      },
    ];
    const [band] = coreBands(adds);
    expect(band.color).not.toBe(GREY_NODE);
    expect(band.colorString).toMatch(/^oklch\(/);
    expect(band.unenriched).toBe(false);
  });

  it("greys a month with adds but no enriched centroid", () => {
    const adds: AddsOverTime[] = [
      { month: "2024-02", count: 5, centroid: null },
    ];
    const [band] = coreBands(adds);
    expect(band.color).toBe(GREY_NODE);
    expect(band.unenriched).toBe(true);
  });

  it("scales intensity by sqrt of relative count", () => {
    const adds: AddsOverTime[] = [
      { month: "2024-01", count: 100, centroid: null },
      { month: "2024-02", count: 25, centroid: null },
    ];
    const bands = coreBands(adds);
    expect(bands[0].intensity).toBeCloseTo(1);
    // sqrt(25/100) = 0.5
    expect(bands[1].intensity).toBeCloseTo(0.5);
  });

  it("handles an all-zero core without dividing by zero", () => {
    const adds: AddsOverTime[] = [
      { month: "2024-01", count: 0, centroid: null },
    ];
    const [band] = coreBands(adds);
    expect(band.intensity).toBe(0);
    expect(band.unenriched).toBe(false);
  });

  it("returns nothing for an empty core", () => {
    expect(coreBands([])).toEqual([]);
  });
});

describe("formatCoreMonth", () => {
  it("formats YYYY-MM to MON 'YY", () => {
    expect(formatCoreMonth("2024-01")).toBe("JAN '24");
    expect(formatCoreMonth("2019-12")).toBe("DEC '19");
  });
});

describe("axisTickIndices", () => {
  it("returns all indices when total fits the count", () => {
    expect(axisTickIndices(3, 5)).toEqual([0, 1, 2]);
  });

  it("always includes first and last", () => {
    const ticks = axisTickIndices(24, 5);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBe(23);
  });

  it("spreads interior ticks evenly", () => {
    expect(axisTickIndices(9, 5)).toEqual([0, 2, 4, 6, 8]);
  });
});
