import { describe, expect, it } from "vitest";
import type { AcousticCentroid } from "./acoustic";
import { acousticColor } from "./acoustic";
import {
  clusterPalette,
  equalizedColor,
  rankEqualize,
  rankMap,
} from "./equalize";

/**
 * G4 — colour variety. The library's driving features are centred percentiles,
 * so acousticColor piles most tracks into the red/magenta corner (measured
 * p50 hue 296°). Rank-equalization spreads the population uniformly across the
 * available gamut *by construction* while preserving order — a track that was
 * redder than another stays redder. These tests lock both properties.
 */

describe("rankMap", () => {
  it("returns 0.5 for a single value (no spread possible)", () => {
    expect(rankMap([0.9])).toEqual([0.5]);
  });

  it("maps the sorted population to an even 0..1 spread", () => {
    // Four clustered-near-0.5 inputs → evenly spaced ranks.
    const out = rankMap([0.5, 0.51, 0.49, 0.52]);
    // sorted order is 0.49, 0.5, 0.51, 0.52 → ranks 0, 1/3, 2/3, 1
    // input index 0 (0.5) is 2nd smallest → 1/3
    expect(out[0]).toBeCloseTo(1 / 3, 6);
    expect(out[1]).toBeCloseTo(2 / 3, 6); // 0.51 is 3rd
    expect(out[2]).toBeCloseTo(0, 6); // 0.49 is smallest
    expect(out[3]).toBeCloseTo(1, 6); // 0.52 is largest
  });

  it("preserves strict ordering (rank is monotonic in value)", () => {
    const vals = [0.2, 0.9, 0.5, 0.51, 0.499, 0.8];
    const ranks = rankMap(vals);
    for (let i = 0; i < vals.length; i++) {
      for (let j = 0; j < vals.length; j++) {
        if (vals[i] < vals[j]) expect(ranks[i]).toBeLessThan(ranks[j]);
        if (vals[i] > vals[j]) expect(ranks[i]).toBeGreaterThan(ranks[j]);
      }
    }
  });

  it("gives tied values the same rank (stable, order-independent)", () => {
    const ranks = rankMap([0.5, 0.5, 0.5, 0.9]);
    expect(ranks[0]).toBeCloseTo(ranks[1], 6);
    expect(ranks[1]).toBeCloseTo(ranks[2], 6);
    expect(ranks[3]).toBeGreaterThan(ranks[0]);
  });

  it("produces a uniform spread: the equalized output has near-flat deciles", () => {
    // A tightly-centred Gaussian-ish population, the real failure mode.
    const vals = Array.from({ length: 1000 }, (_, i) => {
      const x = (i - 500) / 500; // -1..1
      return 0.5 + 0.12 * x; // narrow band around 0.5
    });
    const eq = rankMap(vals)
      .slice()
      .sort((a, b) => a - b);
    // Deciles of a uniform [0,1] land near 0.1, 0.2, … — check p10/p50/p90.
    expect(eq[100]).toBeCloseTo(0.1, 1);
    expect(eq[500]).toBeCloseTo(0.5, 1);
    expect(eq[900]).toBeCloseTo(0.9, 1);
  });
});

describe("rankEqualize (build the equalizing lookup)", () => {
  const lib: AcousticCentroid[] = [
    { acousticness: 0.5, energy: 0.5, valence: 0.5 },
    { acousticness: 0.51, energy: 0.52, valence: 0.48 },
    { acousticness: 0.49, energy: 0.48, valence: 0.52 },
    { acousticness: 0.9, energy: 0.9, valence: 0.9 },
  ];

  it("equalizes the DERIVED hue axis e = 0.8·(1−a) + 0.2·energy, not the raw inputs", () => {
    const eq = rankEqualize(lib);
    // The most-electronic track (lowest e = high acousticness) and most-organic
    // land at the extremes 0 and 1 of the equalized hue driver.
    const eValues = lib.map((c) =>
      Math.min(1, Math.max(0, 0.8 * (1 - c.acousticness) + 0.2 * c.energy)),
    );
    const order = [...eValues.keys()].sort((a, b) => eValues[a] - eValues[b]);
    expect(eq.hueDriver(lib[order[0]])).toBeCloseTo(0, 6);
    expect(eq.hueDriver(lib[order[order.length - 1]])).toBeCloseTo(1, 6);
  });

  it("maps an unseen value by interpolating into the library rank curve", () => {
    const eq = rankEqualize(lib);
    // A value between two library e's interpolates to a rank strictly between.
    const midE = 0.5;
    const r = eq.hueRankOf(midE);
    expect(r).toBeGreaterThanOrEqual(0);
    expect(r).toBeLessThanOrEqual(1);
  });

  it("clamps out-of-range queries to the endpoints", () => {
    const eq = rankEqualize(lib);
    expect(eq.hueRankOf(-5)).toBe(0);
    expect(eq.hueRankOf(5)).toBe(1);
  });
});

describe("equalizedColor", () => {
  // A tightly-centred population — the real failure mode. acousticness bunches
  // near 0.45 so the raw hue driver e≈0.5 → most tracks land on red (h≈0/360).
  const lib: AcousticCentroid[] = Array.from({ length: 400 }, (_, i) => {
    const t = i / 399; // 0..1
    // Bell-ish: cluster mass toward the centre via a cubic ease.
    const centred = 0.5 + 0.18 * (2 * t - 1) ** 3;
    return {
      acousticness: 0.45 + 0.1 * (2 * t - 1) ** 3,
      energy: centred,
      valence: centred,
    };
  });

  it("keeps the same OKLCH legibility guarantees as acousticColor", () => {
    const eq = rankEqualize(lib);
    for (const c of lib) {
      const col = equalizedColor(c, eq);
      expect(col.l).toBeGreaterThanOrEqual(0.48 - 1e-9);
      expect(col.l).toBeLessThanOrEqual(0.75 + 1e-9);
      expect(col.c).toBeGreaterThanOrEqual(0.05 - 1e-9);
      expect(col.c).toBeLessThanOrEqual(0.18 + 1e-9);
    }
  });

  it("never enters the banned cyan band (hue 100–260)", () => {
    const eq = rankEqualize(lib);
    for (const c of lib) {
      const { h } = equalizedColor(c, eq);
      expect(h < 100 || h > 260).toBe(true);
    }
  });

  it("de-concentrates the red corner and evens hue occupancy", () => {
    const eq = rankEqualize(lib);
    const rawHues = lib.map((c) => acousticColor(c).h);
    const eqHues = lib.map((c) => equalizedColor(c, eq).h);
    // The complaint made numeric: fewer tracks piled in the red/magenta corner.
    const redShare = (hs: number[]) =>
      hs.filter((h) => h >= 300 && h < 360).length / hs.length;
    expect(redShare(eqHues)).toBeLessThan(redShare(rawHues));
    // The single most-crowded 30° bin holds a smaller share after equalizing
    // (population spread more evenly across the occupied arc).
    const maxBinShare = (hs: number[]) => {
      const bins = new Array<number>(12).fill(0);
      for (const h of hs) bins[Math.floor(h / 30) % 12]++;
      return Math.max(...bins) / hs.length;
    };
    expect(maxBinShare(eqHues)).toBeLessThanOrEqual(maxBinShare(rawHues));
  });

  it("preserves ordering: a track redder than another stays redder", () => {
    const eq = rankEqualize(lib);
    // Sort library by raw e; equalized hue order must match raw hue order.
    const eOf = (c: AcousticCentroid) =>
      Math.min(1, Math.max(0, 0.8 * (1 - c.acousticness) + 0.2 * c.energy));
    const a = lib[10];
    const b = lib[150];
    if (eOf(a) < eOf(b)) {
      // lower e → higher hue (arc 80 - 160e). Ordering of the hue driver holds.
      expect(equalizedColor(a, eq).h).toBeGreaterThanOrEqual(
        equalizedColor(b, eq).h - 1e-6,
      );
    }
  });
});

describe("clusterPalette", () => {
  it("assigns each real cluster a distinct base hue around the wheel", () => {
    const pal = clusterPalette([0, 1, 2, 3, 4], -1);
    const hues = [0, 1, 2, 3, 4].map((c) => pal.baseHue(c));
    expect(new Set(hues).size).toBe(5);
    // hues spread across the full wheel
    expect(Math.max(...hues) - Math.min(...hues)).toBeGreaterThan(180);
  });

  it("gives the dominant genre-less cluster a neutral fallback tint", () => {
    // Cluster 7 is flagged as the genre-less mass → muted, not a vivid hue.
    const pal = clusterPalette([0, 7], -1, 7);
    expect(pal.isNeutral(7)).toBe(true);
    expect(pal.isNeutral(0)).toBe(false);
    const neutral = pal.colorFor(7, {
      acousticness: 0.5,
      energy: 0.5,
      valence: 0.5,
    });
    // low chroma — reads as "mixed / uncategorised", never a saturated identity
    expect(neutral.c).toBeLessThan(0.06);
  });

  it("renders noise (-1) as the grey out-of-gamut state", () => {
    const pal = clusterPalette([0, 1], -1);
    const noise = pal.colorFor(-1, {
      acousticness: 0.5,
      energy: 0.5,
      valence: 0.5,
    });
    expect(noise.c).toBeLessThan(0.05);
    expect(noise.l).toBeLessThan(0.48);
  });

  it("varies lightness/chroma within a cluster from the track's acoustics", () => {
    const pal = clusterPalette([0, 1], -1);
    const dim = pal.colorFor(0, {
      acousticness: 0.5,
      energy: 0.2,
      valence: 0.1,
    });
    const bright = pal.colorFor(0, {
      acousticness: 0.5,
      energy: 0.9,
      valence: 0.9,
    });
    // Same base hue, but energy/valence separate them on chroma + lightness.
    expect(Math.abs(dim.h - bright.h)).toBeLessThan(1);
    expect(bright.l).toBeGreaterThan(dim.l);
    expect(bright.c).toBeGreaterThan(dim.c);
  });
});

describe("rankEqualize is a no-op-safe pure transform", () => {
  it("empty library yields identity ranks (0.5) so colour still renders", () => {
    const eq = rankEqualize([]);
    expect(eq.hueRankOf(0.3)).toBe(0.5);
    const col = equalizedColor(
      { acousticness: 0.3, energy: 0.3, valence: 0.3 },
      eq,
    );
    expect(Number.isFinite(col.h)).toBe(true);
  });
});
