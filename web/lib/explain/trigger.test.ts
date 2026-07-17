import { describe, expect, it } from "vitest";
import {
  explainTriggerGlyph,
  explainTriggerLabel,
  openTransition,
} from "./trigger";

describe("explainTriggerLabel", () => {
  it("names the metric so screen readers announce what will be explained", () => {
    // Known ref → uses the human term.
    expect(explainTriggerLabel("ari")).toBe("Explain: Ear-vs-maths agreement");
  });

  it("falls back gracefully for an unknown ref", () => {
    expect(explainTriggerLabel("no_such_metric")).toBe("Explain this metric");
  });
});

describe("explainTriggerGlyph", () => {
  it("mirrors the field-guide question-mark treatment", () => {
    expect(explainTriggerGlyph()).toBe("?");
  });
});

describe("openTransition", () => {
  it("animates with an ease-out curve when motion is allowed", () => {
    const t = openTransition(false);
    expect(t.duration).toBeGreaterThan(0);
    expect(Array.isArray(t.ease)).toBe(true);
  });

  it("collapses to an instant, zero-duration transition under reduced motion", () => {
    const t = openTransition(true);
    expect(t.duration).toBe(0);
  });
});
