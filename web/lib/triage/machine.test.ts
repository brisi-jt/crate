import { describe, expect, it } from "vitest";
import {
  currentTrackId,
  initialTriageState,
  reduceTriage,
  type TriageState,
} from "./machine";

const loaded = (queue: number[]): TriageState =>
  reduceTriage(initialTriageState, { type: "LOADED", queue });

describe("triage queue machine", () => {
  it("starts on the first track of a loaded queue", () => {
    const state = loaded([11, 12, 13]);
    expect(currentTrackId(state)).toBe(11);
  });

  it("empty queue has no current track", () => {
    const state = loaded([]);
    expect(currentTrackId(state)).toBeNull();
  });

  it("SKIP moves to the next track without removing the skipped one", () => {
    let state = loaded([11, 12, 13]);
    state = reduceTriage(state, { type: "SKIP" });
    expect(currentTrackId(state)).toBe(12);
    // The whole queue is intact — skip loses nothing.
    expect(state.queue).toEqual([11, 12, 13]);
  });

  it("SKIP cycles from the last track back to the first (queue cycles)", () => {
    let state = loaded([11, 12]);
    state = reduceTriage(state, { type: "SKIP" }); // on 12
    expect(currentTrackId(state)).toBe(12);
    state = reduceTriage(state, { type: "SKIP" }); // wraps to 11
    expect(currentTrackId(state)).toBe(11);
  });

  it("a skipped track comes back around — it is returned later, never lost", () => {
    let state = loaded([11, 12, 13]);
    state = reduceTriage(state, { type: "SKIP" }); // 12
    state = reduceTriage(state, { type: "SKIP" }); // 13
    state = reduceTriage(state, { type: "SKIP" }); // wraps to 11 again
    expect(currentTrackId(state)).toBe(11);
  });

  it("APPLIED removes the filed track and advances to the next in place", () => {
    let state = loaded([11, 12, 13]);
    state = reduceTriage(state, { type: "APPLIED", trackId: 11 });
    expect(state.queue).toEqual([12, 13]);
    expect(currentTrackId(state)).toBe(12);
  });

  it("APPLIED on the last track wraps the position to the new head", () => {
    let state = loaded([11, 12]);
    state = reduceTriage(state, { type: "SKIP" }); // on 12
    state = reduceTriage(state, { type: "APPLIED", trackId: 12 });
    expect(state.queue).toEqual([11]);
    expect(currentTrackId(state)).toBe(11);
  });

  it("APPLIED on an earlier track keeps the current one focused", () => {
    let state = loaded([11, 12, 13]);
    state = reduceTriage(state, { type: "SKIP" }); // on 12
    state = reduceTriage(state, { type: "APPLIED", trackId: 11 });
    expect(currentTrackId(state)).toBe(12);
  });

  it("APPLIED on the only track drains the queue", () => {
    let state = loaded([11]);
    state = reduceTriage(state, { type: "APPLIED", trackId: 11 });
    expect(state.queue).toEqual([]);
    expect(currentTrackId(state)).toBeNull();
    expect(state.drained).toBe(true);
  });

  it("a fresh page appended keeps the current track focused", () => {
    let state = loaded([11, 12]);
    state = reduceTriage(state, { type: "SKIP" }); // on 12
    state = reduceTriage(state, { type: "APPENDED", queue: [13, 14] });
    // The focused track (12) survives the append and stays focused.
    expect(currentTrackId(state)).toBe(12);
    expect(state.queue).toEqual([11, 12, 13, 14]);
  });

  it("LOADED follows the focused track to its new position when it survives", () => {
    let state = loaded([11, 12, 13]);
    state = reduceTriage(state, { type: "SKIP" }); // on 12
    state = reduceTriage(state, { type: "LOADED", queue: [13, 12, 11] });
    expect(currentTrackId(state)).toBe(12);
  });

  it("LOADED clamps when the focused track dropped out", () => {
    let state = loaded([11, 12, 13]);
    state = reduceTriage(state, { type: "SKIP" });
    state = reduceTriage(state, { type: "SKIP" }); // on 13
    state = reduceTriage(state, { type: "LOADED", queue: [11, 12] });
    // 13 gone: clamp to the tail of the new queue.
    expect(currentTrackId(state)).toBe(12);
  });

  it("drained clears once a non-empty queue loads", () => {
    let state = loaded([11]);
    state = reduceTriage(state, { type: "APPLIED", trackId: 11 });
    expect(state.drained).toBe(true);
    state = reduceTriage(state, { type: "LOADED", queue: [20, 21] });
    expect(state.drained).toBe(false);
    expect(currentTrackId(state)).toBe(20);
  });

  it("SKIP on an empty queue is inert", () => {
    let state = loaded([]);
    state = reduceTriage(state, { type: "SKIP" });
    expect(currentTrackId(state)).toBeNull();
  });
});
