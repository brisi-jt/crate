import { describe, expect, it } from "vitest";
import type { PinCandidate } from "./sampler";
import { mulberry32, samplePins } from "./sampler";

/** A tiny pool builder — n candidates spread across `families` families. */
function pool(
  specs: Array<[family: string, salience: number]>,
): PinCandidate[] {
  return specs.map(([family, salience], i) => ({
    family,
    category: family,
    metric_ref: `m_${i}`,
    anchor: `a${i}`,
    line: `line ${i}`,
    dismissible_id: `insights:${family}:a${i}:m_${i}`,
    salience,
  }));
}

describe("mulberry32", () => {
  it("is deterministic for a given seed", () => {
    const a = mulberry32(42);
    const b = mulberry32(42);
    const seqA = [a(), a(), a()];
    const seqB = [b(), b(), b()];
    expect(seqA).toEqual(seqB);
  });

  it("produces different sequences for different seeds", () => {
    const a = mulberry32(1);
    const b = mulberry32(2);
    expect(a()).not.toEqual(b());
  });

  it("stays within [0, 1)", () => {
    const rng = mulberry32(7);
    for (let i = 0; i < 100; i++) {
      const v = rng();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});

describe("samplePins — determinism per seed", () => {
  const candidates = pool([
    ["play_events", 0.9],
    ["saved", 0.8],
    ["feedback", 0.7],
    ["radio", 0.6],
    ["journal", 0.5],
  ]);

  it("returns the same selection twice for the same seed", () => {
    const one = samplePins({ candidates, seed: 123 });
    const two = samplePins({ candidates, seed: 123 });
    expect(one.map((p) => p.dismissible_id)).toEqual(
      two.map((p) => p.dismissible_id),
    );
  });

  it("returns a different order/selection across two distinct seeds", () => {
    // With 5 single-family candidates and maxVisible 3, distinct seeds should
    // (at least sometimes) reorder or reselect. Assert not-identical across a
    // spread of seeds rather than a single pair.
    const base = samplePins({ candidates, seed: 1 }).map(
      (p) => p.dismissible_id,
    );
    const anyDifferent = [2, 3, 4, 5, 6].some((s) => {
      const other = samplePins({ candidates, seed: s }).map(
        (p) => p.dismissible_id,
      );
      return JSON.stringify(other) !== JSON.stringify(base);
    });
    expect(anyDifferent).toBe(true);
  });
});

describe("samplePins — quota (max 1 per family)", () => {
  it("never returns two pins from the same family", () => {
    const candidates = pool([
      ["play_events", 0.9],
      ["play_events", 0.85],
      ["play_events", 0.8],
      ["saved", 0.7],
      ["saved", 0.6],
      ["feedback", 0.5],
    ]);
    for (let seed = 0; seed < 50; seed++) {
      const picked = samplePins({ candidates, seed, maxVisible: 3 });
      const families = picked.map((p) => p.family);
      expect(new Set(families).size).toBe(families.length);
    }
  });

  it("caps output at maxVisible", () => {
    const candidates = pool([
      ["play_events", 0.9],
      ["saved", 0.8],
      ["feedback", 0.7],
      ["radio", 0.6],
      ["journal", 0.5],
      ["top_items", 0.4],
      ["cross_table", 0.3],
    ]);
    const picked = samplePins({ candidates, seed: 9, maxVisible: 3 });
    expect(picked.length).toBe(3);
  });

  it("returns fewer than maxVisible when the pool has fewer families", () => {
    const candidates = pool([
      ["play_events", 0.9],
      ["play_events", 0.8],
    ]);
    const picked = samplePins({ candidates, seed: 3, maxVisible: 3 });
    expect(picked.length).toBe(1); // one family → one pin
  });

  it("returns an empty list for an empty pool", () => {
    expect(samplePins({ candidates: [], seed: 1 })).toEqual([]);
  });
});

describe("samplePins — dismissals", () => {
  it("never returns a dismissed candidate", () => {
    const candidates = pool([
      ["play_events", 0.9],
      ["saved", 0.8],
      ["feedback", 0.7],
    ]);
    const dismissed = new Set([candidates[0].dismissible_id]);
    for (let seed = 0; seed < 30; seed++) {
      const picked = samplePins({ candidates, seed, dismissed, maxVisible: 3 });
      expect(picked.map((p) => p.dismissible_id)).not.toContain(
        candidates[0].dismissible_id,
      );
    }
  });
});

describe("samplePins — salience weighting (elitist)", () => {
  it("favours higher-salience candidates over many seeds", () => {
    // One family so the quota doesn't mask the weighting; two candidates, a
    // strong-salience one and a weak one. Over many seeds the strong one should
    // be chosen far more often.
    const candidates = pool([
      ["play_events", 0.95],
      ["play_events", 0.05],
    ]);
    const strongId = candidates[0].dismissible_id;
    let strongWins = 0;
    const trials = 400;
    for (let seed = 0; seed < trials; seed++) {
      const picked = samplePins({ candidates, seed, maxVisible: 1 });
      if (picked[0]?.dismissible_id === strongId) strongWins++;
    }
    // Elitist weighting (salience^k) → strong should dominate heavily.
    expect(strongWins).toBeGreaterThan(trials * 0.7);
  });
});

describe("samplePins — recently-shown down-weighting", () => {
  it("prefers an unseen candidate over a recently-shown one of equal salience", () => {
    const candidates = pool([
      ["play_events", 0.6], // recently shown
      ["play_events", 0.6], // unseen
    ]);
    const shownId = candidates[0].dismissible_id;
    const freshId = candidates[1].dismissible_id;
    const shownHistory = { [shownId]: 3 }; // shown in the last 3 sessions
    let freshWins = 0;
    const trials = 400;
    for (let seed = 0; seed < trials; seed++) {
      const picked = samplePins({
        candidates,
        seed,
        shownHistory,
        maxVisible: 1,
      });
      if (picked[0]?.dismissible_id === freshId) freshWins++;
    }
    // Equal salience, but the shown one is down-weighted → fresh wins the
    // majority of the time.
    expect(freshWins).toBeGreaterThan(trials * 0.6);
  });
});
