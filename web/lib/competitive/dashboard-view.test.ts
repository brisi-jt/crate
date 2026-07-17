import { describe, expect, it } from "vitest";
import type { DriftComparison } from "@/lib/api/schemas-competitive";
import {
  clockBars,
  driftAxesSorted,
  formatMinutes,
  formatObscurity,
  hasImportedHistory,
  nextRange,
  qualitySubscorePercent,
  rangeParam,
  weekdayBars,
} from "./dashboard-view";

describe("range toggle", () => {
  it("maps each range to its query param", () => {
    expect(rangeParam("all_time")).toBe("all_time");
    expect(rangeParam("since_crate")).toBe("since_crate");
  });

  it("toggles between the two ranges", () => {
    expect(nextRange("all_time")).toBe("since_crate");
    expect(nextRange("since_crate")).toBe("all_time");
  });

  it("only offers the toggle when imported history exists", () => {
    // no imports: all plays are since-crate -> no reason to toggle
    expect(hasImportedHistory({ totalPlays: 200, sinceCratePlays: 200 })).toBe(
      false,
    );
    // imports present: all-time exceeds since-crate
    expect(hasImportedHistory({ totalPlays: 5000, sinceCratePlays: 200 })).toBe(
      true,
    );
  });
});

describe("minutes formatting", () => {
  it("renders whole minutes under an hour", () => {
    expect(formatMinutes({ minutes: 42.6, estimated: false })).toBe("43 min");
  });
  it("renders hours and minutes above an hour", () => {
    expect(formatMinutes({ minutes: 731.5, estimated: true })).toBe(
      "12h 12m (est)",
    );
  });
  it("marks estimates", () => {
    expect(formatMinutes({ minutes: 30, estimated: true })).toContain("est");
    expect(formatMinutes({ minutes: 30, estimated: false })).not.toContain(
      "est",
    );
  });
});

describe("clock + weekday bars", () => {
  it("normalizes 24 hour buckets and flags the peak", () => {
    const hours = Array(24).fill(0);
    hours[11] = 40;
    hours[10] = 30;
    const bars = clockBars(hours, 11);
    expect(bars).toHaveLength(24);
    expect(bars[11].fraction).toBe(1);
    expect(bars[11].peak).toBe(true);
    expect(bars[10].fraction).toBeCloseTo(0.75);
    expect(bars[10].peak).toBe(false);
  });

  it("labels the seven weekdays from Monday", () => {
    const bars = weekdayBars([0, 1, 1, 99, 65, 34, 9]);
    expect(bars).toHaveLength(7);
    expect(bars[0].label).toBe("Mon");
    expect(bars[6].label).toBe("Sun");
    expect(bars[3].fraction).toBe(1); // 99 is the max
  });

  it("survives an all-zero clock (no divide-by-zero)", () => {
    const bars = clockBars(Array(24).fill(0), null);
    expect(bars.every((b) => b.fraction === 0)).toBe(true);
    expect(bars.some((b) => b.peak)).toBe(false);
  });
});

describe("obscurity formatting", () => {
  it("renders a percentage with a mainstream/niche direction", () => {
    expect(formatObscurity(0.3015)).toMatch(/30%/);
    expect(formatObscurity(0.95)).toMatch(/95%/);
  });
  it("handles a null score gracefully", () => {
    expect(formatObscurity(null)).toBe("—");
  });
});

describe("drift axes ordering", () => {
  // biome-ignore-start lint/suspicious/noThenProperty: `then` mirrors the API's past-self axis field.
  const comparison: DriftComparison = {
    axes: [
      { feature: "energy", now: 0.5, then: 0.4, delta: 0.1 },
      { feature: "valence", now: 0.52, then: 0.4, delta: 0.12 },
      { feature: "tempo", now: 0.5, then: 0.51, delta: -0.01 },
    ],
    distance: 0.238,
    biggest_mover: { feature: "valence", delta: 0.12 },
  };
  // biome-ignore-end lint/suspicious/noThenProperty: past-self axis fixture.

  it("sorts axes by absolute movement, biggest first", () => {
    const sorted = driftAxesSorted(comparison.axes);
    expect(sorted[0].feature).toBe("valence");
    expect(sorted[sorted.length - 1].feature).toBe("tempo");
  });
});

describe("quality sub-score percent", () => {
  it("converts a 0..1 sub-score to a rounded percentage", () => {
    expect(qualitySubscorePercent(0.6325)).toBe(63);
    expect(qualitySubscorePercent(1)).toBe(100);
  });
});
