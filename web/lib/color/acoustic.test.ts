import { describe, expect, it } from "vitest";
import {
  acousticColor,
  GREY_NODE,
  oklchString,
  selectionRing,
} from "./acoustic";

/**
 * Worked examples from the design tokens doc §2 — the five archetype
 * playlists. Doc values are rounded (L/c to 2–3 places, hue to integers), so
 * assertions carry matching tolerances.
 */
const ARCHETYPES = [
  {
    name: "Folk",
    input: { acousticness: 0.95, energy: 0.15, valence: 0.45 },
    expected: { l: 0.6, c: 0.07, h: 69 },
  },
  {
    name: "Chill acoustic",
    input: { acousticness: 0.85, energy: 0.25, valence: 0.65 },
    expected: { l: 0.655, c: 0.083, h: 53 },
  },
  {
    name: "Gym",
    input: { acousticness: 0.05, energy: 0.97, valence: 0.7 },
    expected: { l: 0.67, c: 0.176, h: 287 },
  },
  {
    name: "Drill",
    input: { acousticness: 0.08, energy: 0.85, valence: 0.15 },
    expected: { l: 0.52, c: 0.161, h: 295 },
  },
  {
    name: "Sunday morning",
    input: { acousticness: 0.6, energy: 0.35, valence: 0.9 },
    expected: { l: 0.72, c: 0.096, h: 18 },
  },
];

describe("acousticColor", () => {
  for (const { name, input, expected } of ARCHETYPES) {
    it(`matches the ${name} worked example`, () => {
      const color = acousticColor(input);
      expect(color.l).toBeCloseTo(expected.l, 2);
      expect(color.c).toBeCloseTo(expected.c, 2);
      expect(Math.abs(color.h - expected.h)).toBeLessThanOrEqual(0.5);
    });
  }

  it("keeps lightness within the 0.48–0.75 legibility band", () => {
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      const { l } = acousticColor({
        acousticness: 0.5,
        energy: 0.5,
        valence: v,
      });
      expect(l).toBeGreaterThanOrEqual(0.48);
      expect(l).toBeLessThanOrEqual(0.75);
    }
  });

  it("keeps chroma within the 0.05–0.18 band", () => {
    for (const a of [0, 0.5, 1]) {
      for (const e of [0, 0.5, 1]) {
        for (const v of [0, 0.5, 1]) {
          const { c } = acousticColor({
            acousticness: a,
            energy: e,
            valence: v,
          });
          expect(c).toBeGreaterThanOrEqual(0.05 - 1e-9);
          expect(c).toBeLessThanOrEqual(0.18 + 1e-9);
        }
      }
    }
  });

  it("never enters the cyan band (hue 100–260 unused)", () => {
    for (let a = 0; a <= 1; a += 0.05) {
      for (let e = 0; e <= 1; e += 0.25) {
        const { h } = acousticColor({
          acousticness: a,
          energy: e,
          valence: 0.5,
        });
        expect(h < 100 || h > 260).toBe(true);
      }
    }
  });

  it("tapers chroma at high lightness (vivid-happy never goes neon)", () => {
    // Pop archetype: L 0.71 puts it in the high-lightness taper.
    const pop = acousticColor({
      acousticness: 0.147,
      energy: 0.9,
      valence: 0.852,
    });
    expect(pop.c).toBeCloseTo(0.167, 2);
    expect(pop.h).toBeCloseTo(302, 0);
  });
});

describe("grey out-of-gamut state", () => {
  it("sits below both data-ramp floors so unknown can't read as calm", () => {
    expect(GREY_NODE.l).toBeLessThan(0.48);
    expect(GREY_NODE.c).toBeLessThan(0.05);
    expect(oklchString(GREY_NODE)).toBe("oklch(0.42 0.012 265)");
  });
});

describe("selectionRing", () => {
  it("lifts lightness by 0.12 and re-clamps chroma at the new lightness", () => {
    // Indie Rock (tokens §2 extended examples): oklch(0.63 0.128 338).
    const indie = acousticColor({
      acousticness: 0.353,
      energy: 0.6,
      valence: 0.556,
    });
    const ring = selectionRing(indie);
    expect(ring.l).toBeCloseTo(0.75, 2);
    // At L 0.75 the high taper caps chroma at 0.18 − 0.45·0.07 = 0.1485 —
    // above indie's own 0.128, so chroma carries through unclamped.
    expect(ring.c).toBeCloseTo(0.128, 2);
    expect(ring.h).toBeCloseTo(indie.h, 5);
  });
});
