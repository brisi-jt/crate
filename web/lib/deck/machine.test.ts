import { describe, expect, it } from "vitest";
import { currentId, type DeckState, initialDeckState, reduce } from "./machine";

const loaded = (queue: number[]): DeckState =>
  reduce(initialDeckState, { type: "LOADED", queue });

describe("deck machine", () => {
  it("starts on the first candidate of a loaded queue", () => {
    const state = loaded([11, 12, 13]);
    expect(currentId(state)).toBe(11);
    expect(state.playing).toBe(false);
  });

  it("j/k navigation clamps at both ends", () => {
    let state = loaded([11, 12]);
    state = reduce(state, { type: "PREV" });
    expect(currentId(state)).toBe(11); // clamped at start
    state = reduce(state, { type: "NEXT" });
    expect(currentId(state)).toBe(12);
    state = reduce(state, { type: "NEXT" });
    expect(currentId(state)).toBe(12); // clamped at end
    state = reduce(state, { type: "PREV" });
    expect(currentId(state)).toBe(11);
  });

  it("navigation carries the playing intent to the next candidate", () => {
    let state = loaded([11, 12]);
    state = reduce(state, { type: "TOGGLE_PLAY" });
    state = reduce(state, { type: "NEXT" });
    expect(state.playing).toBe(true);
    expect(currentId(state)).toBe(12);
  });

  it("space toggles play/pause; audio end stops it", () => {
    let state = loaded([11]);
    state = reduce(state, { type: "TOGGLE_PLAY" });
    expect(state.playing).toBe(true);
    state = reduce(state, { type: "TOGGLE_PLAY" });
    expect(state.playing).toBe(false);
    state = reduce(state, { type: "TOGGLE_PLAY" });
    state = reduce(state, { type: "AUDIO_ENDED" });
    expect(state.playing).toBe(false);
  });

  it("resolving the current candidate advances to the next in place", () => {
    let state = loaded([11, 12, 13]);
    state = reduce(state, { type: "RESOLVE", id: 11 });
    expect(state.queue).toEqual([12, 13]);
    expect(currentId(state)).toBe(12);
  });

  it("resolving the last candidate clamps to the new tail", () => {
    let state = loaded([11, 12]);
    state = reduce(state, { type: "NEXT" });
    state = reduce(state, { type: "RESOLVE", id: 12 });
    expect(state.queue).toEqual([11]);
    expect(currentId(state)).toBe(11);
  });

  it("resolving an earlier candidate keeps the current one focused", () => {
    let state = loaded([11, 12, 13]);
    state = reduce(state, { type: "NEXT" }); // on 12
    state = reduce(state, { type: "RESOLVE", id: 11 });
    expect(currentId(state)).toBe(12);
  });

  it("resolving the only candidate empties the deck", () => {
    let state = loaded([11]);
    state = reduce(state, { type: "RESOLVE", id: 11 });
    expect(state.queue).toEqual([]);
    expect(currentId(state)).toBeNull();
  });

  it("a reload follows the current candidate to its new rank", () => {
    let state = loaded([11, 12, 13]);
    state = reduce(state, { type: "NEXT" }); // on 12
    state = reduce(state, { type: "LOADED", queue: [13, 12, 11] });
    expect(currentId(state)).toBe(12);
    expect(state.index).toBe(1);
  });

  it("a reload that dropped the current candidate clamps the index", () => {
    let state = loaded([11, 12, 13]);
    state = reduce(state, { type: "NEXT" });
    state = reduce(state, { type: "NEXT" }); // on 13
    state = reduce(state, { type: "LOADED", queue: [11, 12] });
    expect(currentId(state)).toBe(12);
  });

  it("events on an empty deck are inert", () => {
    let state = loaded([]);
    expect(currentId(state)).toBeNull();
    state = reduce(state, { type: "NEXT" });
    state = reduce(state, { type: "TOGGLE_PLAY" });
    expect(currentId(state)).toBeNull();
    expect(state.playing).toBe(false);
  });
});
