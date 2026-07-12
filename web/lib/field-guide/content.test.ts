import { beforeEach, describe, expect, it } from "vitest";
import { useUiStore } from "@/lib/store/ui";
import { fieldGuideContent } from "./content";

// ---------------------------------------------------------------- content

describe("fieldGuideContent — playlist graph", () => {
  it("returns playlist graph content with live numbers", () => {
    const result = fieldGuideContent("playlists", {
      playlistCount: 12,
      edgeCount: 34,
      subsetCount: 2,
    });
    expect(result.title).toBe("Playlist graph");
    expect(result.summary).toContain("12 playlists");
    expect(result.summary).toContain("34 edges");
    expect(result.summary).toContain("2 subset pairs");
    expect(result.legend.length).toBe(3);
    expect(result.prompts.length).toBeGreaterThan(0);
  });

  it("omits subset mention from summary when none exist", () => {
    const result = fieldGuideContent("playlists", {
      playlistCount: 5,
      edgeCount: 8,
      subsetCount: 0,
    });
    expect(result.summary).not.toContain("subset");
  });

  it("uses singular 'pair' when exactly one subset", () => {
    const result = fieldGuideContent("playlists", {
      playlistCount: 3,
      edgeCount: 2,
      subsetCount: 1,
    });
    expect(result.summary).toContain("1 subset pair");
  });

  it("renders dash for undefined stats", () => {
    const result = fieldGuideContent("playlists", {});
    expect(result.summary).toContain("— playlists");
  });
});

describe("fieldGuideContent — track field", () => {
  it("includes track count and cluster count", () => {
    const result = fieldGuideContent("tracks", {
      trackCount: 820,
      clusterCount: 7,
      ari: 0.61,
    });
    expect(result.title).toBe("Track field");
    expect(result.summary).toContain("820 tracks");
    expect(result.summary).toContain("7 clusters");
    expect(result.summary).toContain("ARI 0.61");
    expect(result.legend.length).toBe(3);
    expect(result.prompts.length).toBeGreaterThan(0);
  });

  it("omits ARI when null", () => {
    const result = fieldGuideContent("tracks", {
      trackCount: 400,
      clusterCount: 4,
      ari: null,
    });
    expect(result.summary).not.toContain("ARI");
  });
});

describe("fieldGuideContent — artist galaxy", () => {
  it("shows partial coverage when not all artists shown", () => {
    const result = fieldGuideContent("artists", {
      artistsShown: 150,
      artistsTotal: 300,
    });
    expect(result.title).toBe("Artist galaxy");
    expect(result.summary).toContain("150");
    expect(result.summary).toContain("300");
    expect(result.summary).toContain("of");
    expect(result.legend.length).toBe(3);
  });

  it("shows simple count when all artists fit", () => {
    const result = fieldGuideContent("artists", {
      artistsShown: 80,
      artistsTotal: 80,
    });
    expect(result.summary).not.toContain("of");
    expect(result.summary).toContain("80 artists");
  });

  it("appends bridge count when provided", () => {
    const result = fieldGuideContent("artists", {
      artistsShown: 80,
      artistsTotal: 80,
      bridgeCount: 6,
    });
    expect(result.summary).toContain("6 bridging");
  });
});

describe("fieldGuideContent — frontier", () => {
  it("returns compact frontier content with live counts", () => {
    const result = fieldGuideContent("frontier", {
      territoryCount: 34,
      frontierCount: 9,
    });
    expect(result.title).toBe("Frontier");
    expect(result.summary).toContain("34 territory");
    expect(result.summary).toContain("9 frontier");
    expect(result.legend.length).toBe(3);
    // The panel is already a reading — no extra analysis prompts.
    expect(result.prompts).toEqual([]);
  });

  it("covers territory, frontier, and seed in the legend", () => {
    const result = fieldGuideContent("frontier", {});
    const labels = result.legend.map((l) => l.label);
    expect(labels).toEqual(["Territory", "Frontier", "Seed"]);
  });

  it("renders dash for undefined counts", () => {
    const result = fieldGuideContent("frontier", {});
    expect(result.summary).toContain("— territory");
  });
});

// ---------------------------------------------------------------- store

describe("field guide store", () => {
  beforeEach(() => {
    useUiStore.setState({
      fieldGuideExpanded: {},
      fieldGuideFirstVisit: {},
    });
  });

  it("defaults to expanded (first-visit implicit) for any mode", () => {
    const { fieldGuideExpanded, fieldGuideFirstVisit } = useUiStore.getState();
    // No entry means first visit — guide is expanded by default.
    expect(fieldGuideExpanded.playlists).toBeUndefined();
    expect(fieldGuideFirstVisit.playlists).toBeUndefined();
  });

  it("setFieldGuideExpanded records expanded=false and marks visited", () => {
    useUiStore.getState().setFieldGuideExpanded("playlists", false);
    const state = useUiStore.getState();
    expect(state.fieldGuideExpanded.playlists).toBe(false);
    expect(state.fieldGuideFirstVisit.playlists).toBe(true);
  });

  it("persists state per mode independently", () => {
    useUiStore.getState().setFieldGuideExpanded("playlists", false);
    useUiStore.getState().setFieldGuideExpanded("tracks", true);
    const state = useUiStore.getState();
    expect(state.fieldGuideExpanded.playlists).toBe(false);
    expect(state.fieldGuideExpanded.tracks).toBe(true);
    expect(state.fieldGuideExpanded.artists).toBeUndefined();
  });

  it("re-expanding a mode updates the record", () => {
    useUiStore.getState().setFieldGuideExpanded("playlists", false);
    useUiStore.getState().setFieldGuideExpanded("playlists", true);
    expect(useUiStore.getState().fieldGuideExpanded.playlists).toBe(true);
    expect(useUiStore.getState().fieldGuideFirstVisit.playlists).toBe(true);
  });

  it("frontier is a first-class field guide mode", () => {
    // First visit: no entries, so the guide defaults to expanded.
    expect(useUiStore.getState().fieldGuideFirstVisit.frontier).toBeUndefined();
    useUiStore.getState().setFieldGuideExpanded("frontier", false);
    const state = useUiStore.getState();
    expect(state.fieldGuideExpanded.frontier).toBe(false);
    expect(state.fieldGuideFirstVisit.frontier).toBe(true);
    // Canvas modes are untouched.
    expect(state.fieldGuideExpanded.playlists).toBeUndefined();
  });
});
