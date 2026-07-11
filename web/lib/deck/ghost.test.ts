import { describe, expect, it } from "vitest";
import { GHOST_BASE_GAP, GHOST_SPREAD, ghostOffset } from "./ghost";

const playlist = { energy: 0.88, valence: 0.7, acousticness: 0.05 };

describe("ghost position mapping", () => {
  it("an identical candidate sits up-left of the target at the base gap", () => {
    const offset = ghostOffset(playlist, playlist, 17.8);
    const distance = Math.hypot(offset.dx, offset.dy);
    expect(distance).toBeCloseTo(17.8 + GHOST_BASE_GAP, 5);
    expect(offset.dx).toBeLessThan(0); // up-left convention
    expect(offset.dy).toBeLessThan(0);
  });

  it("a more acoustic candidate drifts right; lower energy drifts down", () => {
    const candidate = { energy: 0.4, valence: 0.6, acousticness: 0.9 };
    const offset = ghostOffset(candidate, playlist, 17.8);
    expect(offset.dx).toBeGreaterThan(0); // +acousticness -> +x
    expect(offset.dy).toBeGreaterThan(0); // -energy -> +y (screen down)
  });

  it("a higher-energy, more electronic candidate drifts up-left", () => {
    const candidate = { energy: 1.0, valence: 0.6, acousticness: 0.0 };
    const near = { energy: 0.5, valence: 0.6, acousticness: 0.5 };
    const offset = ghostOffset(candidate, near, 12);
    expect(offset.dx).toBeLessThan(0);
    expect(offset.dy).toBeLessThan(0);
  });

  it("distance grows with acoustic difference but stays bounded", () => {
    const near = ghostOffset(
      { energy: 0.86, valence: 0.7, acousticness: 0.07 },
      playlist,
      17.8,
    );
    const far = ghostOffset(
      { energy: 0.1, valence: 0.2, acousticness: 1.0 },
      playlist,
      17.8,
    );
    const nearDist = Math.hypot(near.dx, near.dy);
    const farDist = Math.hypot(far.dx, far.dy);
    expect(farDist).toBeGreaterThan(nearDist);
    expect(farDist).toBeLessThanOrEqual(
      17.8 + GHOST_BASE_GAP + GHOST_SPREAD + 1e-9,
    );
  });

  it("is deterministic", () => {
    const candidate = { energy: 0.4, valence: 0.6, acousticness: 0.9 };
    expect(ghostOffset(candidate, playlist, 17.8)).toEqual(
      ghostOffset(candidate, playlist, 17.8),
    );
  });

  it("hand-computed example", () => {
    // deltas: x = 0.35 - 0.05 = 0.3 (acousticness), y = 0.88 - 0.48 = 0.4 (energy drop)
    const candidate = { energy: 0.48, valence: 0.7, acousticness: 0.35 };
    const offset = ghostOffset(candidate, playlist, 10);
    const norm = Math.hypot(0.3, 0.4); // 0.5
    const distance = 10 + GHOST_BASE_GAP + GHOST_SPREAD * Math.min(1, norm);
    expect(Math.hypot(offset.dx, offset.dy)).toBeCloseTo(distance, 5);
    expect(offset.dx).toBeCloseTo((0.3 / norm) * distance, 5);
    expect(offset.dy).toBeCloseTo((0.4 / norm) * distance, 5);
  });
});
