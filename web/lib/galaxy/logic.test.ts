import { describe, expect, it } from "vitest";
import {
  artistGalaxyResponseSchema,
  frontierResponseSchema,
} from "@/lib/api/schemas";
import {
  bridgingArtists,
  galaxyEdgeDash,
  galaxyEdgeWidth,
  togglePin,
} from "./logic";

describe("galaxy edge styling", () => {
  it("co-playlist edges scale width with shared playlists, solid line", () => {
    expect(galaxyEdgeWidth("co_playlist", 0)).toBeCloseTo(0.75);
    expect(galaxyEdgeWidth("co_playlist", 4)).toBeCloseTo(0.75 + 2.25 * 0.5);
    expect(galaxyEdgeWidth("co_playlist", 8)).toBeCloseTo(3);
    expect(galaxyEdgeWidth("co_playlist", 40)).toBeCloseTo(3); // clamped
    expect(galaxyEdgeDash("co_playlist")).toBeNull();
  });

  it("similarity edges are dashed and scale with match strength", () => {
    expect(galaxyEdgeDash("similarity")).toEqual([3, 2]);
    expect(galaxyEdgeWidth("similarity", 0)).toBeCloseTo(1);
    expect(galaxyEdgeWidth("similarity", 1)).toBeCloseTo(2.5);
  });
});

describe("bridge pins", () => {
  it("pins up to two playlists, replacing the oldest", () => {
    expect(togglePin([], 1)).toEqual([1]);
    expect(togglePin([1], 2)).toEqual([1, 2]);
    expect(togglePin([1, 2], 3)).toEqual([2, 3]); // oldest pin rotates out
  });

  it("clicking a pinned playlist unpins it", () => {
    expect(togglePin([1, 2], 1)).toEqual([2]);
    expect(togglePin([1], 1)).toEqual([]);
  });
});

describe("bridging artists", () => {
  const nodes = [
    { id: "a", playlist_ids: [1, 2] },
    { id: "b", playlist_ids: [1] },
    { id: "c", playlist_ids: [2, 3] },
  ];

  it("no pins means no highlight", () => {
    expect(bridgingArtists(nodes, [])).toBeNull();
  });

  it("one pin highlights that playlist's artists", () => {
    expect(bridgingArtists(nodes, [1])).toEqual(new Set(["a", "b"]));
  });

  it("two pins highlight only the artists connecting both", () => {
    expect(bridgingArtists(nodes, [1, 2])).toEqual(new Set(["a"]));
    expect(bridgingArtists(nodes, [1, 3])).toEqual(new Set());
  });
});

describe("phase 9 contracts", () => {
  it("parses the artist galaxy payload shape", () => {
    const payload = {
      nodes: [
        {
          id: "artist a",
          name: "Artist A",
          track_count: 3,
          playlist_count: 2,
          playlist_ids: [1, 3],
          centroid: { acousticness: 0.43, energy: 0.43, valence: 0.43 },
          genres: ["ambient techno", "dub"],
          tracks: [{ id: 11, name: "Track 1" }],
          similar: [{ name: "Artist B", weight: 0.8, in_library: true }],
        },
      ],
      edges: [
        {
          source: "artist a",
          target: "artist b",
          kind: "co_playlist",
          weight: 1,
        },
        {
          source: "artist a",
          target: "artist b",
          kind: "similarity",
          weight: 0.8,
        },
      ],
      coverage: {
        artists_total: 3,
        artists_shown: 3,
        edges_total: 4,
        edges_shown: 4,
      },
      _links: { self: { href: "/v1/graph/artists" } },
    };
    const parsed = artistGalaxyResponseSchema.parse(payload);
    expect(parsed.nodes[0].centroid?.energy).toBe(0.43);
    expect(parsed.edges[1].kind).toBe("similarity");
  });

  it("parses the frontier payload shape", () => {
    const payload = {
      territory: [
        {
          genre_id: 1,
          name: "house",
          enao_rank: 1,
          presence: 1,
          matched_artists: 1,
        },
      ],
      frontier: [
        {
          genre_id: 3,
          name: "electro",
          enao_rank: 3,
          score: 0.75,
          presence: 0,
          adjacent_to: ["house", "techno"],
          exemplars: [{ name: "x1", weight: 1 }],
        },
      ],
      coverage: { library_artists: 2, matched_artists: 2 },
      _links: { self: { href: "/v1/discovery/frontier" } },
    };
    const parsed = frontierResponseSchema.parse(payload);
    expect(parsed.frontier[0].exemplars[0].name).toBe("x1");
    expect(parsed.territory[0].presence).toBe(1);
  });
});
