import { describe, expect, it } from "vitest";
import {
  applyBody,
  canApply,
  emptySelection,
  reduceSelection,
} from "./selection";

describe("triage destination selection", () => {
  it("starts empty", () => {
    const s = emptySelection();
    expect(s.destinationIds).toEqual([]);
    expect(canApply(s)).toBe(false);
  });

  it("toggles a destination on and off", () => {
    let s = emptySelection();
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 5 });
    expect(s.destinationIds).toEqual([5]);
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 7 });
    expect(s.destinationIds).toEqual([5, 7]);
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 5 });
    expect(s.destinationIds).toEqual([7]);
  });

  it("an already-in destination is still selectable (spec)", () => {
    let s = emptySelection();
    // The reducer does not know about already_in — the panel greys it but the
    // selection accepts it, because filing into it again is a valid no-op the
    // server tolerates.
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 9 });
    expect(s.destinationIds).toEqual([9]);
  });

  it("can apply once any destination is chosen", () => {
    let s = emptySelection();
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 5 });
    expect(canApply(s)).toBe(true);
  });

  it("can apply with a new playlist even when no existing destination is picked", () => {
    let s = emptySelection();
    s = reduceSelection(s, {
      type: "SET_NEW_PLAYLIST",
      newPlaylist: { name: "Bassline", seedTrackIds: [1, 2] },
    });
    expect(canApply(s)).toBe(true);
  });

  it("cannot apply with an empty new-playlist name", () => {
    let s = emptySelection();
    s = reduceSelection(s, {
      type: "SET_NEW_PLAYLIST",
      newPlaylist: { name: "   ", seedTrackIds: [] },
    });
    expect(canApply(s)).toBe(false);
  });

  it("assembles a multi-destination apply body", () => {
    let s = emptySelection();
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 5 });
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 7 });
    s = reduceSelection(s, { type: "SET_UNSAVE", unsave: true });
    const body = applyBody(s, 40441);
    expect(body).toEqual({
      track_id: 40441,
      destination_playlist_ids: [5, 7],
      unsave: true,
    });
  });

  it("includes a trimmed new_playlist with the filed track always in the seed", () => {
    let s = emptySelection();
    s = reduceSelection(s, {
      type: "SET_NEW_PLAYLIST",
      newPlaylist: { name: "  Rap  ", seedTrackIds: [1, 40441, 2] },
    });
    const body = applyBody(s, 40441);
    expect(body.new_playlist?.name).toBe("Rap");
    // The filed track is always part of the seed and never duplicated.
    expect(body.new_playlist?.seed_track_ids).toContain(40441);
    expect(
      body.new_playlist?.seed_track_ids?.filter((id) => id === 40441),
    ).toHaveLength(1);
  });

  it("omits destination_playlist_ids when none are selected", () => {
    let s = emptySelection();
    s = reduceSelection(s, {
      type: "SET_NEW_PLAYLIST",
      newPlaylist: { name: "Solo", seedTrackIds: [] },
    });
    const body = applyBody(s, 40441);
    expect(body.destination_playlist_ids).toBeUndefined();
  });

  it("clearing the new playlist drops it from the body", () => {
    let s = emptySelection();
    s = reduceSelection(s, {
      type: "SET_NEW_PLAYLIST",
      newPlaylist: { name: "Rap", seedTrackIds: [] },
    });
    s = reduceSelection(s, { type: "SET_NEW_PLAYLIST", newPlaylist: null });
    s = reduceSelection(s, { type: "TOGGLE_DEST", playlistId: 3 });
    const body = applyBody(s, 40441);
    expect(body.new_playlist).toBeUndefined();
    expect(body.destination_playlist_ids).toEqual([3]);
  });
});
