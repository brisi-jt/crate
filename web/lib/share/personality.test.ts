import { describe, expect, it } from "vitest";
import { personalityLabel } from "./personality";

/**
 * The "crate DNA" personality label — derived purely from the library's
 * dominant sound and top genres. Tasteful, deterministic, never cringe.
 */
describe("personalityLabel", () => {
  const base = {
    energy: 0.5,
    valence: 0.5,
    acousticness: 0.5,
    danceability: 0.5,
    obscurity: 0.5,
    topGenres: ["house", "techno"],
  };

  it("is deterministic — same input yields the same label", () => {
    const a = personalityLabel(base);
    const b = personalityLabel(base);
    expect(a).toEqual(b);
  });

  it("names a high-energy, high-valence library as bright and driving", () => {
    const label = personalityLabel({ ...base, energy: 0.9, valence: 0.9 });
    expect(label.toLowerCase()).toMatch(
      /bright|radiant|euphoric|sunlit|kinetic|electric/,
    );
  });

  it("names a low-energy, low-valence, acoustic library as brooding and organic", () => {
    const label = personalityLabel({
      ...base,
      energy: 0.1,
      valence: 0.1,
      acousticness: 0.9,
    });
    expect(label.toLowerCase()).toMatch(
      /brooding|shadow|melancholy|dusk|somber|hushed|dim/,
    );
  });

  it("reflects deep obscurity in the label", () => {
    const label = personalityLabel({ ...base, obscurity: 0.95 });
    expect(label.toLowerCase()).toMatch(
      /deep|obscure|underground|hidden|cratedigger|niche|fringe/,
    );
  });

  it("reflects a mainstream (low-obscurity) library too", () => {
    const label = personalityLabel({ ...base, obscurity: 0.05 });
    expect(label.toLowerCase()).toMatch(
      /chart|mainstream|popular|open|familiar/,
    );
  });

  it("never returns an empty or absurdly long label", () => {
    const label = personalityLabel({ ...base, energy: 0.7, valence: 0.3 });
    expect(label.length).toBeGreaterThan(2);
    expect(label.length).toBeLessThanOrEqual(48);
  });

  it("handles a null-genre library without throwing", () => {
    const label = personalityLabel({ ...base, topGenres: [] });
    expect(label.length).toBeGreaterThan(2);
  });

  it("is stable across the whole feature grid (no undefined words)", () => {
    for (const energy of [0, 0.5, 1]) {
      for (const valence of [0, 0.5, 1]) {
        for (const obscurity of [0, 0.5, 1]) {
          const label = personalityLabel({
            ...base,
            energy,
            valence,
            obscurity,
          });
          expect(label).not.toMatch(/undefined|NaN/);
          expect(label.length).toBeGreaterThan(2);
        }
      }
    }
  });
});
