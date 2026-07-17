import { describe, expect, it } from "vitest";
import type { GalaxyNode, MapPoint } from "@/lib/api/schemas";
import {
  artistCardModel,
  clampCardPosition,
  fingerprintBars,
  trackCardModel,
} from "./hover-card";

/**
 * G1 — rich hover-card view models. The card shell is one component; the data
 * it shows differs per node type. Mapping node → card model is pure (no DOM,
 * no image), so the fields, fingerprint bars, and viewport clamping are
 * unit-tested and the component stays a thin renderer.
 */

const TRACK: MapPoint = {
  track_id: 42,
  name: "Midnight City",
  artist: "M83",
  x: 0,
  y: 0,
  cluster: 3,
  album_image_url: "https://cdn/art.jpg",
  features: { acousticness: 0.1, energy: 0.85, valence: 0.6 },
  playlist_ids: [1, 2, 3],
};

describe("trackCardModel", () => {
  it("maps the track's names, art, cluster and membership count", () => {
    const m = trackCardModel(TRACK);
    expect(m.title).toBe("Midnight City");
    expect(m.subtitle).toBe("M83");
    expect(m.imageUrl).toBe("https://cdn/art.jpg");
    expect(m.clusterId).toBe(3);
    expect(m.playlistCount).toBe(3);
  });

  it("carries a fingerprint readout from the track's features", () => {
    const m = trackCardModel(TRACK);
    // energy/valence/acousticness rendered as compact readouts.
    expect(m.fingerprint).toEqual([
      { label: "NRG", value: 0.85 },
      { label: "VAL", value: 0.6 },
      { label: "ACO", value: 0.1 },
    ]);
  });

  it("has no fingerprint when features are absent", () => {
    const m = trackCardModel({ ...TRACK, features: null });
    expect(m.fingerprint).toBeNull();
  });

  it("null image url when the album has no art yet", () => {
    const m = trackCardModel({ ...TRACK, album_image_url: null });
    expect(m.imageUrl).toBeNull();
  });

  it("noise cluster (−1) reads as no cluster", () => {
    const m = trackCardModel({ ...TRACK, cluster: -1 });
    expect(m.clusterId).toBeNull();
  });
});

const ARTIST: GalaxyNode = {
  id: "m83",
  name: "M83",
  track_count: 12,
  playlist_count: 4,
  playlist_ids: [1, 2],
  centroid: { acousticness: 0.1, energy: 0.85, valence: 0.6 },
  image_url: "https://cdn/m83.jpg",
  genres: ["dream pop", "shoegaze", "electronic", "synthpop"],
  tracks: [{ id: 1, name: "A" }],
  similar: [
    { name: "Tycho", weight: 0.9, in_library: true },
    { name: "Boards of Canada", weight: 0.8, in_library: false },
    { name: "Air", weight: 0.7, in_library: true },
    { name: "Zero 7", weight: 0.5, in_library: false },
  ],
};

describe("artistCardModel", () => {
  it("maps photo, name, counts and top genres (capped at 3)", () => {
    const m = artistCardModel(ARTIST);
    expect(m.title).toBe("M83");
    expect(m.imageUrl).toBe("https://cdn/m83.jpg");
    expect(m.trackCount).toBe(12);
    expect(m.playlistCount).toBe(4);
    expect(m.genres).toEqual(["dream pop", "shoegaze", "electronic"]);
  });

  it("lists up to three similar artists with in-library marks", () => {
    const m = artistCardModel(ARTIST);
    expect(m.similar).toEqual([
      { name: "Tycho", inLibrary: true },
      { name: "Boards of Canada", inLibrary: false },
      { name: "Air", inLibrary: true },
    ]);
  });

  it("tolerates a photo-less / genre-less artist", () => {
    const m = artistCardModel({
      ...ARTIST,
      image_url: null,
      genres: [],
      similar: [],
    });
    expect(m.imageUrl).toBeNull();
    expect(m.genres).toEqual([]);
    expect(m.similar).toEqual([]);
  });
});

describe("fingerprintBars", () => {
  it("clamps values to 0..1 and preserves label order", () => {
    const bars = fingerprintBars({
      acousticness: 1.4,
      energy: -0.2,
      valence: 0.5,
    });
    expect(bars).toEqual([
      { label: "NRG", value: 0 },
      { label: "VAL", value: 0.5 },
      { label: "ACO", value: 1 },
    ]);
  });
});

describe("clampCardPosition", () => {
  const CARD = { width: 260, height: 120 };

  it("offsets down-right of the cursor by default", () => {
    const p = clampCardPosition(100, 100, CARD, { width: 1000, height: 800 });
    expect(p.left).toBe(118);
    expect(p.top).toBe(118);
  });

  it("flips left when the card would overflow the right edge", () => {
    const p = clampCardPosition(980, 100, CARD, { width: 1000, height: 800 });
    // card kept fully inside: right edge ≤ container width − margin
    expect(p.left + CARD.width).toBeLessThanOrEqual(1000);
  });

  it("flips up when the card would overflow the bottom edge", () => {
    const p = clampCardPosition(100, 790, CARD, { width: 1000, height: 800 });
    expect(p.top + CARD.height).toBeLessThanOrEqual(800);
  });

  it("respects a right inset (docked panel) as the effective right edge", () => {
    const p = clampCardPosition(700, 100, CARD, {
      width: 1000,
      height: 800,
      rightInset: 400,
    });
    // usable width is 600; card must stay left of it
    expect(p.left + CARD.width).toBeLessThanOrEqual(600);
  });
});
