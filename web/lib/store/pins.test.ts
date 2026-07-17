import { beforeEach, describe, expect, it } from "vitest";
import { usePinsStore } from "./pins";

function reset() {
  usePinsStore.setState({
    dismissed: [],
    hidden: false,
    seed: 42,
    shownHistory: {},
  });
}

describe("pins store — dismissal", () => {
  beforeEach(reset);

  it("dismisses an id once, idempotently", () => {
    usePinsStore.getState().dismiss("a");
    usePinsStore.getState().dismiss("a");
    expect(usePinsStore.getState().dismissed).toEqual(["a"]);
  });

  it("restoreAll clears dismissals and un-hides", () => {
    usePinsStore.setState({ dismissed: ["a", "b"], hidden: true });
    usePinsStore.getState().restoreAll();
    expect(usePinsStore.getState().dismissed).toEqual([]);
    expect(usePinsStore.getState().hidden).toBe(false);
  });
});

describe("pins store — rotation seed", () => {
  beforeEach(reset);

  it("reshuffle rolls a new seed", () => {
    const before = usePinsStore.getState().seed;
    // Roll until it differs (random, but collision is astronomically unlikely
    // across a couple of rolls).
    let changed = false;
    for (let i = 0; i < 5 && !changed; i++) {
      usePinsStore.getState().reshuffle();
      changed = usePinsStore.getState().seed !== before;
    }
    expect(changed).toBe(true);
  });
});

describe("pins store — shown history", () => {
  beforeEach(reset);

  it("records shown ids, incrementing their count", () => {
    usePinsStore.getState().recordShown(["a", "b"]);
    usePinsStore.getState().recordShown(["a"]);
    expect(usePinsStore.getState().shownHistory).toEqual({ a: 2, b: 1 });
  });

  it("ignores an empty record", () => {
    usePinsStore.getState().recordShown([]);
    expect(usePinsStore.getState().shownHistory).toEqual({});
  });
});
