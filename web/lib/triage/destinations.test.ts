import { describe, expect, it } from "vitest";
import {
  destinationsBody,
  eligibleCount,
  excludedIds,
  filterDestinations,
  initDestinations,
  isDirty,
  reduceDestinations,
  visibleIds,
} from "./destinations";

const DESTS = [
  { id: 1, name: "Gym", excluded: false },
  { id: 2, name: "Chill", excluded: true },
  { id: 3, name: "Late Night Drives", excluded: false },
];

describe("initDestinations", () => {
  it("eligible = the inverse of the server's excluded flag", () => {
    const s = initDestinations(DESTS);
    expect(s.eligible[1]).toBe(true); // Gym eligible
    expect(s.eligible[2]).toBe(false); // Chill excluded
    expect(s.eligible[3]).toBe(true);
  });

  it("starts clean and un-searched", () => {
    const s = initDestinations(DESTS);
    expect(s.search).toBe("");
    expect(isDirty(s)).toBe(false);
  });
});

describe("counts + excluded set", () => {
  it("eligibleCount counts checked playlists across the whole set", () => {
    expect(eligibleCount(initDestinations(DESTS))).toBe(2); // Gym + Late Night
  });

  it("excludedIds are the unchecked ones, sorted", () => {
    expect(excludedIds(initDestinations(DESTS))).toEqual([2]);
  });
});

describe("TOGGLE", () => {
  it("flips one playlist's eligibility and marks dirty", () => {
    let s = initDestinations(DESTS);
    s = reduceDestinations(s, { type: "TOGGLE", id: 1 });
    expect(s.eligible[1]).toBe(false);
    expect(isDirty(s)).toBe(true);
    expect(excludedIds(s)).toEqual([1, 2]);
  });

  it("toggling back to the original set is clean again", () => {
    let s = initDestinations(DESTS);
    s = reduceDestinations(s, { type: "TOGGLE", id: 1 });
    s = reduceDestinations(s, { type: "TOGGLE", id: 1 });
    expect(isDirty(s)).toBe(false);
  });
});

describe("SEARCH + filtered bulk ops", () => {
  it("filterDestinations matches on name, case-insensitively", () => {
    const s = reduceDestinations(initDestinations(DESTS), {
      type: "SEARCH",
      query: "night",
    });
    expect(visibleIds(s)).toEqual([3]); // "Late Night Drives"
    expect(filterDestinations(DESTS, "GYM").map((d) => d.id)).toEqual([1]);
  });

  it("SELECT_ALL only affects the currently-visible (filtered) set", () => {
    let s = reduceDestinations(initDestinations(DESTS), {
      type: "SEARCH",
      query: "chill",
    });
    // Chill (id 2) is excluded; select-all over the filter makes it eligible.
    s = reduceDestinations(s, { type: "SELECT_ALL" });
    expect(s.eligible[2]).toBe(true);
    expect(s.eligible[1]).toBe(true); // untouched (still eligible from init)
    expect(s.eligible[3]).toBe(true);
  });

  it("SELECT_NONE excludes only the visible set", () => {
    let s = reduceDestinations(initDestinations(DESTS), {
      type: "SEARCH",
      query: "gym",
    });
    s = reduceDestinations(s, { type: "SELECT_NONE" });
    expect(s.eligible[1]).toBe(false); // Gym now excluded
    expect(s.eligible[3]).toBe(true); // Late Night untouched
    expect(excludedIds(s)).toEqual([1, 2]);
  });

  it("INVERT flips only the visible set", () => {
    // No search -> whole set visible. Gym+Late eligible, Chill excluded -> invert.
    let s = initDestinations(DESTS);
    s = reduceDestinations(s, { type: "INVERT" });
    expect(s.eligible[1]).toBe(false);
    expect(s.eligible[2]).toBe(true);
    expect(s.eligible[3]).toBe(false);
  });
});

describe("destinationsBody", () => {
  it("PUT body carries the excluded ids", () => {
    let s = initDestinations(DESTS);
    s = reduceDestinations(s, { type: "TOGGLE", id: 3 }); // exclude Late Night
    expect(destinationsBody(s)).toEqual({ excluded_playlist_ids: [2, 3] });
  });

  it("all eligible -> empty excluded list", () => {
    let s = initDestinations(DESTS);
    s = reduceDestinations(s, { type: "SELECT_ALL" }); // whole set visible
    expect(destinationsBody(s)).toEqual({ excluded_playlist_ids: [] });
  });
});
