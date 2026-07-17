import { describe, expect, it } from "vitest";
import type { DestinationSuggestion } from "@/lib/api/schemas";
import { EVIDENCE_LABELS, evidenceRows } from "./evidence";

const suggestion = (
  evidence: DestinationSuggestion["evidence"],
): DestinationSuggestion => ({
  playlist_id: 1,
  name: "rock",
  rank: 0.4,
  already_in: false,
  evidence,
});

describe("evidence view-model", () => {
  it("renders one row per named signal in a stable canonical order", () => {
    const rows = evidenceRows(
      suggestion([
        { kind: "vibe_match", score: 0.1, summary: "v", detail: {} },
        { kind: "sonic_fit", score: 0.9, summary: "s", detail: {} },
        { kind: "placement_history", score: 0.2, summary: "p", detail: {} },
        { kind: "artist_overlap", score: 0.3, summary: "a", detail: {} },
      ]),
    );
    // Canonical order: sonic_fit, artist_overlap, placement_history, vibe_match.
    expect(rows.map((r) => r.kind)).toEqual([
      "sonic_fit",
      "artist_overlap",
      "placement_history",
      "vibe_match",
    ]);
  });

  it("labels each row from the signal, never a blended score", () => {
    const rows = evidenceRows(
      suggestion([
        {
          kind: "sonic_fit",
          score: 0.9,
          summary: "Similar energy.",
          detail: {},
        },
      ]),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe(EVIDENCE_LABELS.sonic_fit);
    expect(rows[0].summary).toBe("Similar energy.");
    // The row carries the per-signal score only — no combined/rank field leaks in.
    expect(rows[0]).not.toHaveProperty("rank");
    expect(rows[0]).not.toHaveProperty("blended");
  });

  it("keeps only the four known signals, ignoring stray kinds", () => {
    const rows = evidenceRows(
      suggestion([
        { kind: "sonic_fit", score: 0.9, summary: "s", detail: {} },
        // A future/unknown kind should not surface as an unlabeled row.
        {
          kind: "mystery" as unknown as "sonic_fit",
          score: 0.5,
          summary: "?",
          detail: {},
        },
      ]),
    );
    expect(rows.map((r) => r.kind)).toEqual(["sonic_fit"]);
  });

  it("carries the per-signal strength for the bar fill", () => {
    const rows = evidenceRows(
      suggestion([
        { kind: "artist_overlap", score: 0.42, summary: "3 here", detail: {} },
      ]),
    );
    expect(rows[0].strength).toBe(0.42);
  });
});
