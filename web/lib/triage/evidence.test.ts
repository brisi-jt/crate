import { describe, expect, it } from "vitest";
import type { DestinationSuggestion } from "@/lib/api/schemas";
import { EVIDENCE_LABELS, evidenceDigest, evidenceRows } from "./evidence";

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

describe("evidence digest (one-line inline summary)", () => {
  it("summarises the two STRONGEST signals, strongest first", () => {
    const parts = evidenceDigest(
      suggestion([
        {
          kind: "sonic_fit",
          score: 0.92,
          summary: "similar energy+acousticness",
          detail: {},
        },
        {
          kind: "artist_overlap",
          score: 0.6,
          summary: "4 tracks by this artist here",
          detail: {},
        },
        {
          kind: "placement_history",
          score: 0.1,
          summary: "rarely filed here",
          detail: {},
        },
        {
          kind: "vibe_match",
          score: 0.05,
          summary: "weak name match",
          detail: {},
        },
      ]),
    );
    // Two rows: sonic_fit (0.92) then artist_overlap (0.6) — the two strongest.
    expect(parts).toHaveLength(2);
    expect(parts[0].label).toBe(EVIDENCE_LABELS.sonic_fit);
    expect(parts[0].summary).toBe("similar energy+acousticness");
    expect(parts[0].score).toBe(92); // rounded 0..100 for the "·92" readout
    expect(parts[1].label).toBe(EVIDENCE_LABELS.artist_overlap);
  });

  it("returns fewer parts when fewer signals exist — never a bare row", () => {
    const parts = evidenceDigest(
      suggestion([
        { kind: "sonic_fit", score: 0.5, summary: "some fit", detail: {} },
      ]),
    );
    expect(parts).toHaveLength(1);
    expect(parts[0].label).toBe(EVIDENCE_LABELS.sonic_fit);
  });

  it("is empty when a suggestion carries no known signals", () => {
    expect(evidenceDigest(suggestion([]))).toEqual([]);
  });

  it("drops unknown kinds before picking the strongest two", () => {
    const parts = evidenceDigest(
      suggestion([
        {
          kind: "mystery" as unknown as "sonic_fit",
          score: 0.99,
          summary: "?",
          detail: {},
        },
        { kind: "artist_overlap", score: 0.4, summary: "2 here", detail: {} },
        { kind: "vibe_match", score: 0.3, summary: "name", detail: {} },
      ]),
    );
    // The 0.99 mystery kind is not a labeled signal — excluded; the two real
    // signals (0.4, 0.3) form the digest.
    expect(parts.map((p) => p.label)).toEqual([
      EVIDENCE_LABELS.artist_overlap,
      EVIDENCE_LABELS.vibe_match,
    ]);
  });
});
