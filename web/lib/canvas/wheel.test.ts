import { describe, expect, it } from "vitest";
import {
  classifyWheelEvent,
  normaliseDelta,
  panDelta,
  zoomFactor,
} from "./wheel";

// ---------------------------------------------------------------------------
// normaliseDelta
// ---------------------------------------------------------------------------
describe("normaliseDelta", () => {
  it("returns pixel-mode values unchanged (deltaMode 0)", () => {
    expect(normaliseDelta(10, 0)).toBe(10);
    expect(normaliseDelta(-5.5, 0)).toBe(-5.5);
    expect(normaliseDelta(0, 0)).toBe(0);
  });

  it("multiplies by 16 for line mode (deltaMode 1)", () => {
    expect(normaliseDelta(3, 1)).toBe(48);
    expect(normaliseDelta(-2, 1)).toBe(-32);
  });

  it("multiplies by 400 for page mode (deltaMode 2)", () => {
    expect(normaliseDelta(1, 2)).toBe(400);
    expect(normaliseDelta(-0.5, 2)).toBe(-200);
  });

  it("treats unknown deltaMode like pixels", () => {
    // Future browser modes should default to no scaling.
    expect(normaliseDelta(7, 99)).toBe(7);
  });
});

// ---------------------------------------------------------------------------
// classifyWheelEvent
// ---------------------------------------------------------------------------
describe("classifyWheelEvent", () => {
  it("routes ctrlKey=true to zoom", () => {
    expect(classifyWheelEvent(true)).toBe("zoom");
  });

  it("routes ctrlKey=false to pan", () => {
    expect(classifyWheelEvent(false)).toBe("pan");
  });
});

// ---------------------------------------------------------------------------
// panDelta
// ---------------------------------------------------------------------------
describe("panDelta", () => {
  it("converts screen pixels to graph coords by dividing by zoom k", () => {
    // At zoom k=2, 100 screen pixels = 50 graph units.
    expect(panDelta(100, 2)).toBe(50);
    expect(panDelta(-60, 3)).toBeCloseTo(-20);
  });

  it("at zoom k=1, graph and screen units match", () => {
    expect(panDelta(40, 1)).toBe(40);
    expect(panDelta(-15.5, 1)).toBe(-15.5);
  });

  it("scales inversely: smaller zoom → larger graph-coord move per pixel", () => {
    const atHalfZoom = panDelta(10, 0.5);
    const atFullZoom = panDelta(10, 1);
    expect(atHalfZoom).toBeGreaterThan(atFullZoom);
    expect(atHalfZoom).toBe(20);
  });

  it("does not return NaN or Infinity for extreme-but-valid inputs", () => {
    const result = panDelta(1_000_000, 0.01);
    expect(Number.isFinite(result)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// zoomFactor
// ---------------------------------------------------------------------------
describe("zoomFactor", () => {
  it("returns a factor < 1 for positive deltaY (scroll down = zoom out)", () => {
    expect(zoomFactor(100)).toBeLessThan(1);
  });

  it("returns a factor > 1 for negative deltaY (scroll up = zoom in)", () => {
    expect(zoomFactor(-100)).toBeGreaterThan(1);
  });

  it("returns exactly 1 for deltaY 0 (no movement)", () => {
    expect(zoomFactor(0)).toBe(1);
  });

  it("is continuous around zero (no discontinuity)", () => {
    const small = zoomFactor(1);
    expect(small).toBeGreaterThan(0.99);
    expect(small).toBeLessThan(1);
  });

  it("large positive deltaY gives a very small factor (fast zoom-out)", () => {
    // 500px scroll: factor ≈ e^(-0.5) ≈ 0.607
    const f = zoomFactor(500);
    expect(f).toBeGreaterThan(0);
    expect(f).toBeLessThan(0.7);
  });

  it("large negative deltaY gives a large factor (fast zoom-in)", () => {
    const f = zoomFactor(-500);
    expect(f).toBeGreaterThan(1.4);
  });
});
