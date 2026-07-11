import { describe, expect, it } from "vitest";
import {
  ARM_DECAY_MS,
  armReducer,
  IDLE,
  isArmed,
  secondsRemaining,
} from "./arm";

describe("arm/commit state machine", () => {
  it("starts idle", () => {
    expect(isArmed(IDLE)).toBe(false);
    expect(secondsRemaining(IDLE, 0)).toBeNull();
  });

  it("arming opens a decay window", () => {
    const state = armReducer(IDLE, { type: "arm", now: 1000 });
    expect(isArmed(state)).toBe(true);
    expect(secondsRemaining(state, 1000)).toBe(10);
    expect(secondsRemaining(state, 1000 + 3200)).toBe(7);
  });

  it("stays armed on ticks inside the window", () => {
    let state = armReducer(IDLE, { type: "arm", now: 0 });
    state = armReducer(state, { type: "tick", now: ARM_DECAY_MS - 1 });
    expect(isArmed(state)).toBe(true);
  });

  it("decays to idle when the window elapses", () => {
    let state = armReducer(IDLE, { type: "arm", now: 0 });
    state = armReducer(state, { type: "tick", now: ARM_DECAY_MS });
    expect(state).toEqual(IDLE);
  });

  it("any manifest change disarms", () => {
    const armed = armReducer(IDLE, { type: "arm", now: 0 });
    expect(armReducer(armed, { type: "manifest-changed" })).toEqual(IDLE);
  });

  it("explicit disarm returns to idle", () => {
    const armed = armReducer(IDLE, { type: "arm", now: 0 });
    expect(armReducer(armed, { type: "disarm" })).toEqual(IDLE);
  });

  it("commit consumes the arm", () => {
    const armed = armReducer(IDLE, { type: "arm", now: 0 });
    expect(armReducer(armed, { type: "commit" })).toEqual(IDLE);
  });

  it("re-arming resets the decay window", () => {
    let state = armReducer(IDLE, { type: "arm", now: 0 });
    state = armReducer(state, { type: "arm", now: 8000 });
    state = armReducer(state, { type: "tick", now: 10_000 });
    expect(isArmed(state)).toBe(true);
    expect(secondsRemaining(state, 10_000)).toBe(8);
  });

  it("ticks while idle stay idle", () => {
    expect(armReducer(IDLE, { type: "tick", now: 99_999 })).toEqual(IDLE);
  });
});
