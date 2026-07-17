import { describe, expect, it } from "vitest";
import {
  cleanupBody,
  cleanupSelectedCount,
  initCleanup,
  reduceCleanup,
} from "./cleanup";

const songs = [
  { trackId: 1, name: "A" },
  { trackId: 2, name: "B" },
  { trackId: 3, name: "C" },
];

describe("triage removal-popup selection", () => {
  it("every song starts UNCHECKED (spec: default unchecked)", () => {
    const s = initCleanup(songs);
    expect(cleanupSelectedCount(s)).toBe(0);
    for (const song of songs) expect(s.checked[song.trackId]).toBe(false);
  });

  it("toggles one song", () => {
    let s = initCleanup(songs);
    s = reduceCleanup(s, { type: "TOGGLE", trackId: 2 });
    expect(s.checked[2]).toBe(true);
    expect(cleanupSelectedCount(s)).toBe(1);
    s = reduceCleanup(s, { type: "TOGGLE", trackId: 2 });
    expect(s.checked[2]).toBe(false);
  });

  it("select all checks every song", () => {
    let s = initCleanup(songs);
    s = reduceCleanup(s, { type: "SELECT_ALL" });
    expect(cleanupSelectedCount(s)).toBe(3);
  });

  it("select none clears every song", () => {
    let s = initCleanup(songs);
    s = reduceCleanup(s, { type: "SELECT_ALL" });
    s = reduceCleanup(s, { type: "SELECT_NONE" });
    expect(cleanupSelectedCount(s)).toBe(0);
  });

  it("builds a liked-mode cleanup body from the checked songs", () => {
    let s = initCleanup(songs);
    s = reduceCleanup(s, { type: "TOGGLE", trackId: 1 });
    s = reduceCleanup(s, { type: "TOGGLE", trackId: 3 });
    const body = cleanupBody(s, { source: "liked" });
    expect(body).toEqual({ source: "liked", track_ids: [1, 3] });
  });

  it("builds a playlist-mode cleanup body carrying the source playlist id", () => {
    let s = initCleanup(songs);
    s = reduceCleanup(s, { type: "SELECT_ALL" });
    const body = cleanupBody(s, { source: "playlist", playlistId: 341 });
    expect(body).toEqual({
      source: "playlist",
      playlist_id: 341,
      track_ids: [1, 2, 3],
    });
  });

  it("returns null when nothing is checked (no-op cleanup)", () => {
    const s = initCleanup(songs);
    expect(cleanupBody(s, { source: "liked" })).toBeNull();
  });
});
