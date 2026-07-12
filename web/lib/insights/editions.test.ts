import { describe, expect, it } from "vitest";
import type { EditionSummary } from "@/lib/api/schemas";
import {
  editionBandState,
  editionLabel,
  formatWeek,
  narrativeTint,
} from "./editions";

function summary(edition_number: number, id = edition_number): EditionSummary {
  return {
    id,
    edition_number,
    week_start: "2026-07-06T00:00:00",
    generated_at: "2026-07-12T15:23:24",
    owned_only: true,
    line_count: 3,
  };
}

describe("editionBandState", () => {
  it("reports empty with no editions", () => {
    expect(editionBandState([])).toEqual({ kind: "empty" });
  });

  it("classifies edition 1 as baseline", () => {
    const state = editionBandState([summary(1)]);
    expect(state.kind).toBe("baseline");
  });

  it("classifies a later edition as delta", () => {
    const state = editionBandState([summary(3), summary(2), summary(1)]);
    expect(state.kind).toBe("delta");
    if (state.kind === "delta") {
      expect(state.latest.edition_number).toBe(3);
    }
  });

  it("picks the highest edition number as latest regardless of order", () => {
    const state = editionBandState([summary(1), summary(5), summary(3)]);
    expect(state.kind).toBe("delta");
    if (state.kind === "delta") {
      expect(state.latest.edition_number).toBe(5);
    }
  });
});

describe("narrativeTint", () => {
  it("maps known kinds to tints", () => {
    expect(narrativeTint("dormancy")).toBe("rose");
    expect(narrativeTint("entropy")).toBe("amber");
    expect(narrativeTint("fingerprint")).toBe("sage");
    expect(narrativeTint("baseline")).toBe("neutral");
    expect(narrativeTint("steady")).toBe("neutral");
  });

  it("defaults unknown kinds to neutral", () => {
    expect(narrativeTint("mystery")).toBe("neutral");
  });
});

describe("editionLabel / formatWeek", () => {
  it("builds the band label", () => {
    expect(editionLabel(summary(3))).toBe("EDITION 3 · WEEK OF 06 JUL 2026");
  });

  it("formats an ISO week start", () => {
    expect(formatWeek("2026-07-06T00:00:00")).toBe("WEEK OF 06 JUL 2026");
  });

  it("handles a garbage date without throwing", () => {
    expect(formatWeek("not-a-date")).toBe("WEEK OF —");
  });
});
