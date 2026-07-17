import { describe, expect, it } from "vitest";
import type { FlowArc } from "@/lib/api/schemas-competitive";
import {
  arcReducer,
  buildArcRows,
  initialArcState,
  isPermutation,
} from "./flow-arc";

const preview: FlowArc = {
  playlist_id: 249,
  name: "?",
  mood: "rising",
  suggested_order: [3, 1, 2],
  current_flow: 33.14,
  suggested_flow: 47.14,
  adjacent_artist_repeats: 0,
  _links: { self: { href: "/x" }, apply: { href: "/x/apply" } },
};

describe("arc reducer", () => {
  it("starts idle on the default mood", () => {
    expect(initialArcState.status).toBe("idle");
    expect(initialArcState.mood).toBe("rising");
  });

  it("changing mood resets any loaded preview (a new order must be fetched)", () => {
    const withPreview = arcReducer(initialArcState, {
      type: "loaded",
      preview,
    });
    const next = arcReducer(withPreview, { type: "setMood", mood: "peak" });
    expect(next.mood).toBe("peak");
    expect(next.preview).toBeNull();
    expect(next.status).toBe("idle");
  });

  it("loading a preview holds the order for apply", () => {
    const next = arcReducer(initialArcState, { type: "loaded", preview });
    expect(next.status).toBe("previewing");
    expect(next.preview?.suggested_order).toEqual([3, 1, 2]);
  });

  it("apply moves to applying, then applied clears the preview", () => {
    const previewing = arcReducer(initialArcState, { type: "loaded", preview });
    const applying = arcReducer(previewing, { type: "applying" });
    expect(applying.status).toBe("applying");
    const applied = arcReducer(applying, { type: "applied" });
    expect(applied.status).toBe("applied");
    expect(applied.preview).toBeNull();
  });

  it("a stale error surfaces a recoverable message without losing the mood", () => {
    const previewing = arcReducer(
      { ...initialArcState, mood: "falling" },
      { type: "loaded", preview: { ...preview, mood: "falling" } },
    );
    const stale = arcReducer(previewing, {
      type: "error",
      message: "The playlist changed — re-preview before applying.",
    });
    expect(stale.status).toBe("error");
    expect(stale.error).toMatch(/re-preview/);
    expect(stale.mood).toBe("falling");
  });

  it("re-previewing after an error returns to previewing", () => {
    const errored = arcReducer(
      { ...initialArcState, status: "error", error: "boom" },
      { type: "loaded", preview },
    );
    expect(errored.status).toBe("previewing");
    expect(errored.error).toBeNull();
  });
});

describe("isPermutation guard", () => {
  it("accepts a re-ordering of the same ids", () => {
    expect(isPermutation([1, 2, 3], [3, 1, 2])).toBe(true);
  });
  it("rejects a different set", () => {
    expect(isPermutation([1, 2, 3], [3, 1, 4])).toBe(false);
    expect(isPermutation([1, 2, 3], [1, 2])).toBe(false);
  });
});

describe("buildArcRows — before/after view", () => {
  it("maps ids to a current-vs-suggested position table", () => {
    const current = [
      { track_id: 1, name: "A", artist: "X" },
      { track_id: 2, name: "B", artist: "Y" },
      { track_id: 3, name: "C", artist: "Z" },
    ];
    const rows = buildArcRows(current, [3, 1, 2]);
    expect(rows).toHaveLength(3);
    // suggested row 0 is track 3 ("C"), which was at current position 3 (1-based)
    expect(rows[0]).toMatchObject({
      track_id: 3,
      name: "C",
      suggestedPos: 1,
      currentPos: 3,
    });
    expect(rows[1]).toMatchObject({
      track_id: 1,
      suggestedPos: 2,
      currentPos: 1,
    });
    // moved flag: track that changed position
    expect(rows[0].moved).toBe(true);
    // track 2 was at current position 2, suggested position 3 -> moved
    expect(rows[2]).toMatchObject({
      track_id: 2,
      currentPos: 2,
      suggestedPos: 3,
      moved: true,
    });
  });

  it("marks a track that keeps its position as not moved", () => {
    const current = [
      { track_id: 1, name: "A", artist: "X" },
      { track_id: 2, name: "B", artist: "Y" },
    ];
    // suggested keeps track 1 first -> position 1 in both
    const rows = buildArcRows(current, [1, 2]);
    expect(rows[0]).toMatchObject({ track_id: 1, moved: false });
    expect(rows[1]).toMatchObject({ track_id: 2, moved: false });
  });

  it("drops suggested ids missing from the current roster (defensive)", () => {
    const current = [{ track_id: 1, name: "A", artist: "X" }];
    const rows = buildArcRows(current, [1, 99]);
    expect(rows).toHaveLength(1);
    expect(rows[0].track_id).toBe(1);
  });
});
