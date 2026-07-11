import { beforeEach, describe, expect, it } from "vitest";
import { openListeningDeck, useDeckStore } from "./deck";
import { useUiStore } from "./ui";

function resetStores() {
  useUiStore.setState({
    rightPanel: null,
    paletteOpen: false,
    includeFollowed: false,
    mapMode: "playlists",
    clusterOverlay: false,
    selectedPlaylistId: null,
    selectedTracks: [],
  });
  useDeckStore.setState({
    queue: [],
    index: 0,
    playing: false,
    playlistId: null,
  });
}

describe("map mode", () => {
  beforeEach(resetStores);

  it("defaults to the playlist graph", () => {
    expect(useUiStore.getState().mapMode).toBe("playlists");
    expect(useUiStore.getState().clusterOverlay).toBe(false);
  });

  it("switches between graph and field", () => {
    useUiStore.getState().setMapMode("tracks");
    expect(useUiStore.getState().mapMode).toBe("tracks");
    useUiStore.getState().setMapMode("playlists");
    expect(useUiStore.getState().mapMode).toBe("playlists");
  });

  it("mode survives panel and palette churn", () => {
    useUiStore.getState().setMapMode("tracks");
    useUiStore.getState().openStats();
    useUiStore.getState().setPaletteOpen(true);
    useUiStore.getState().popLayer();
    useUiStore.getState().popLayer();
    expect(useUiStore.getState().mapMode).toBe("tracks");
  });

  it("opening the listening deck snaps the map back to the playlist graph", () => {
    useUiStore.getState().setMapMode("tracks");
    openListeningDeck(7);
    expect(useUiStore.getState().mapMode).toBe("playlists");
    expect(useUiStore.getState().selectedPlaylistId).toBe(7);
    expect(useDeckStore.getState().playlistId).toBe(7);
  });
});

describe("track card panel", () => {
  beforeEach(resetStores);

  it("docks as the right panel and closes the palette", () => {
    useUiStore.getState().setPaletteOpen(true);
    useUiStore.getState().openTrack(42);
    expect(useUiStore.getState().rightPanel).toEqual({
      kind: "track",
      trackId: 42,
    });
    expect(useUiStore.getState().paletteOpen).toBe(false);
  });

  it("replaces any other right panel (one at a time)", () => {
    useUiStore.getState().openStats();
    useUiStore.getState().openTrack(42);
    expect(useUiStore.getState().rightPanel).toEqual({
      kind: "track",
      trackId: 42,
    });
  });

  it("Escape pops it like any other panel", () => {
    useUiStore.getState().openTrack(42);
    useUiStore.getState().popLayer();
    expect(useUiStore.getState().rightPanel).toBeNull();
  });
});
