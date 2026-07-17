import { describe, expect, it } from "vitest";
import type { AcousticCentroid } from "@/lib/color/acoustic";
import {
  auraCentroid,
  CARD_HEIGHT,
  CARD_WIDTH,
  legendFooter,
  shareFilename,
  topGenreLabels,
} from "./card-view";

describe("card dimensions", () => {
  it("is the fixed story format (1080×1350)", () => {
    expect(CARD_WIDTH).toBe(1080);
    expect(CARD_HEIGHT).toBe(1350);
  });
});

describe("shareFilename", () => {
  it("builds a kebab, dated, kind-tagged filename", () => {
    const name = shareFilename("dna", new Date("2026-07-17T12:00:00Z"));
    expect(name).toMatch(/^crate-dna-2026-07-17\.png$/);
  });
  it("sanitizes a free-form title into the slug", () => {
    const name = shareFilename(
      "Listening Clock!",
      new Date("2026-07-17T00:00:00Z"),
    );
    expect(name).toBe("crate-listening-clock-2026-07-17.png");
  });
});

describe("auraCentroid", () => {
  it("means the centroids of the library into one acoustic aura", () => {
    const centroids: AcousticCentroid[] = [
      { acousticness: 0.2, energy: 0.8, valence: 0.6 },
      { acousticness: 0.4, energy: 0.6, valence: 0.4 },
    ];
    const aura = auraCentroid(centroids);
    expect(aura?.acousticness).toBeCloseTo(0.3);
    expect(aura?.energy).toBeCloseTo(0.7);
    expect(aura?.valence).toBeCloseTo(0.5);
  });

  it("returns null for an empty library (nothing to average)", () => {
    expect(auraCentroid([])).toBeNull();
  });

  it("ignores null centroids", () => {
    const aura = auraCentroid([
      { acousticness: 0.2, energy: 0.8, valence: 0.6 },
      null,
    ]);
    expect(aura).toEqual({ acousticness: 0.2, energy: 0.8, valence: 0.6 });
  });
});

describe("legendFooter", () => {
  it("resolves the three colour-axis explanations for the card footer", () => {
    const legend = legendFooter();
    // hue / chroma / lightness = organic-electronic / energy / mood
    expect(legend.length).toBeGreaterThanOrEqual(3);
    for (const item of legend) {
      expect(item.label).toBeTruthy();
      expect(item.detail).toBeTruthy();
    }
  });
});

describe("topGenreLabels", () => {
  it("caps and uppercases the top genres", () => {
    const labels = topGenreLabels(
      ["house", "techno", "ambient", "dnb", "trance", "idm"],
      4,
    );
    expect(labels).toHaveLength(4);
    expect(labels[0]).toBe("HOUSE");
  });
  it("handles fewer genres than the cap", () => {
    expect(topGenreLabels(["house"], 4)).toEqual(["HOUSE"]);
  });
  it("handles an empty genre list", () => {
    expect(topGenreLabels([], 4)).toEqual([]);
  });
});
