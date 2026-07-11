import { describe, expect, it } from "vitest";
import { deckPhase, runSummary, runYieldedNothing } from "./empty-state";

describe("deckPhase", () => {
  it("loads while the queue query is on its first fetch", () => {
    expect(
      deckPhase({
        pending: true,
        failed: false,
        itemCount: 0,
        hasCurrent: false,
      }),
    ).toBe("loading");
  });

  it("surfaces a failed queue load instead of pretending it's empty", () => {
    expect(
      deckPhase({
        pending: false,
        failed: true,
        itemCount: 0,
        hasCurrent: false,
      }),
    ).toBe("error");
  });

  it("shows the candidate card whenever one is under review", () => {
    expect(
      deckPhase({
        pending: false,
        failed: false,
        itemCount: 5,
        hasCurrent: true,
      }),
    ).toBe("card");
  });

  it("zero resolved candidates = the unsurveyed empty state (verifier D3)", () => {
    expect(
      deckPhase({
        pending: false,
        failed: false,
        itemCount: 0,
        hasCurrent: false,
      }),
    ).toBe("unsurveyed");
  });

  it("a drained queue that had candidates = reviewed, not unsurveyed", () => {
    expect(
      deckPhase({
        pending: false,
        failed: false,
        itemCount: 3,
        hasCurrent: false,
      }),
    ).toBe("reviewed");
  });
});

describe("run readouts", () => {
  it("sums both generation sources into one readout", () => {
    expect(
      runSummary({
        generated_lastfm: 9,
        generated_reccobeats: 3,
        resolved: 5,
        previews_resolved: 4,
      }),
    ).toBe("GENERATED 12 · RESOLVED 5 · PREVIEWS 4");
  });

  it("flags a pass that produced nothing reviewable", () => {
    expect(
      runYieldedNothing({
        generated_lastfm: 4,
        generated_reccobeats: 0,
        resolved: 0,
        previews_resolved: 0,
      }),
    ).toBe(true);
    expect(
      runYieldedNothing({
        generated_lastfm: 0,
        generated_reccobeats: 2,
        resolved: 2,
        previews_resolved: 1,
      }),
    ).toBe(false);
  });
});
