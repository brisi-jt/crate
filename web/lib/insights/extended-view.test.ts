import { describe, expect, it } from "vitest";
import {
  formatClock,
  formatRate,
  hasPlayHistory,
  isExtendedSectionEmpty,
  orderMoodBands,
  topContexts,
} from "./extended-view";

describe("formatRate", () => {
  it("renders a fraction as a whole-number percent", () => {
    expect(formatRate(0.6667)).toBe("67%");
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(1)).toBe("100%");
  });

  it("renders an em dash for a null rate (empty table)", () => {
    expect(formatRate(null)).toBe("—");
  });
});

describe("formatClock", () => {
  it("renders an hour as a 24h clock label", () => {
    expect(formatClock(0)).toBe("00:00");
    expect(formatClock(9)).toBe("09:00");
    expect(formatClock(23)).toBe("23:00");
  });

  it("renders an em dash for a null peak hour", () => {
    expect(formatClock(null)).toBe("—");
  });
});

describe("orderMoodBands", () => {
  it("orders the day bands morning → night regardless of input order", () => {
    const bands = [
      { band: "night", count: 1, mean_energy: 0.5, mean_valence: 0.5 },
      { band: "morning", count: 2, mean_energy: 0.5, mean_valence: 0.5 },
      { band: "evening", count: 3, mean_energy: 0.5, mean_valence: 0.5 },
      { band: "afternoon", count: 4, mean_energy: 0.5, mean_valence: 0.5 },
    ];
    expect(orderMoodBands(bands).map((b) => b.band)).toEqual([
      "morning",
      "afternoon",
      "evening",
      "night",
    ]);
  });

  it("keeps unknown bands at the end", () => {
    const bands = [
      { band: "weird", count: 1, mean_energy: 0.5, mean_valence: 0.5 },
      { band: "morning", count: 2, mean_energy: 0.5, mean_valence: 0.5 },
    ];
    expect(orderMoodBands(bands).map((b) => b.band)).toEqual([
      "morning",
      "weird",
    ]);
  });
});

describe("topContexts", () => {
  it("sorts contexts by share descending", () => {
    const contexts = [
      { context: "album", count: 10, share: 0.1 },
      { context: "playlist", count: 60, share: 0.6 },
      { context: "artist", count: 30, share: 0.3 },
    ];
    expect(topContexts(contexts).map((c) => c.context)).toEqual([
      "playlist",
      "artist",
      "album",
    ]);
  });
});

describe("hasPlayHistory", () => {
  it("is true when there are more total plays than since-crate plays", () => {
    expect(
      hasPlayHistory({
        play_events: 5000,
        since_crate_plays: 199,
        total_saved: 0,
        top_snapshots: 0,
      }),
    ).toBe(true);
  });

  it("is false when all plays are since-crate (no import yet)", () => {
    expect(
      hasPlayHistory({
        play_events: 199,
        since_crate_plays: 199,
        total_saved: 0,
        top_snapshots: 0,
      }),
    ).toBe(false);
  });
});

describe("isExtendedSectionEmpty", () => {
  it("flags a section with a zero total as empty", () => {
    expect(isExtendedSectionEmpty(0)).toBe(true);
    expect(isExtendedSectionEmpty(5)).toBe(false);
  });
});
