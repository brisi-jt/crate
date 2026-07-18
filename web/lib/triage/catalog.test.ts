import { describe, expect, it } from "vitest";
import type { QueueTrack } from "@/lib/api/schemas";
import {
  emptyCatalog,
  lookupTrack,
  reduceCatalog,
  type TrackCatalog,
} from "./catalog";

const track = (id: number, name: string): QueueTrack => ({
  track_id: id,
  spotify_id: `sp-${id}`,
  name,
  artist: `${name} artist`,
  album_image_url: `https://img/${id}.jpg`,
});

describe("triage track catalog", () => {
  it("a page-0 load populates the catalog", () => {
    const cat = reduceCatalog(emptyCatalog("liked:0"), {
      type: "PAGE",
      key: "liked:0",
      items: [track(11, "Locust"), track(12, "Aenima")],
    });
    expect(lookupTrack(cat, 11)?.name).toBe("Locust");
    expect(lookupTrack(cat, 12)?.name).toBe("Aenima");
  });

  it("a later page MERGES without losing earlier entries", () => {
    let cat = reduceCatalog(emptyCatalog("liked:0"), {
      type: "PAGE",
      key: "liked:0",
      items: [track(11, "Locust")],
    });
    cat = reduceCatalog(cat, {
      type: "PAGE",
      key: "liked:0",
      items: [track(50, "Vicarious")],
    });
    // The prefetched page must not evict the earlier (current) track.
    expect(lookupTrack(cat, 11)?.name).toBe("Locust");
    expect(lookupTrack(cat, 50)?.name).toBe("Vicarious");
  });

  it("a source/filter key switch RESETS the catalog", () => {
    let cat = reduceCatalog(emptyCatalog("liked:0"), {
      type: "PAGE",
      key: "liked:0",
      items: [track(11, "Locust")],
    });
    // Switching the source key drops the old catalog entirely.
    cat = reduceCatalog(cat, {
      type: "PAGE",
      key: "playlist:0",
      items: [track(99, "Other")],
    });
    expect(lookupTrack(cat, 11)).toBeNull(); // gone with the old source
    expect(lookupTrack(cat, 99)?.name).toBe("Other");
    expect(cat.key).toBe("playlist:0");
  });

  it("the CURRENT track survives a prefetch that advances to a later page", () => {
    // Page 0 holds the current track; the machine nears the tail and prefetches
    // page 1. The card looks the current track up by id — it must still resolve.
    let cat = reduceCatalog(emptyCatalog("liked:0"), {
      type: "PAGE",
      key: "liked:0",
      items: [track(40441, "Locust"), track(40442, "Davidian")],
    });
    const currentId = 40441;
    cat = reduceCatalog(cat, {
      type: "PAGE",
      key: "liked:0",
      items: [track(50000, "Imperium"), track(50001, "Halo")],
    });
    // Post-prefetch, the current track's name is still resolvable (Bug 1).
    expect(lookupTrack(cat, currentId)?.name).toBe("Locust");
    expect(lookupTrack(cat, currentId)?.artist).toBe("Locust artist");
  });

  it("re-seeing a page (a re-fetch of the same offset) is idempotent", () => {
    let cat = reduceCatalog(emptyCatalog("liked:0"), {
      type: "PAGE",
      key: "liked:0",
      items: [track(11, "Locust")],
    });
    cat = reduceCatalog(cat, {
      type: "PAGE",
      key: "liked:0",
      items: [track(11, "Locust")],
    });
    expect(cat.byId.size).toBe(1);
    expect(lookupTrack(cat, 11)?.name).toBe("Locust");
  });

  it("lookupTrack returns null for an unknown id", () => {
    const cat: TrackCatalog = emptyCatalog("liked:0");
    expect(lookupTrack(cat, 12345)).toBeNull();
  });
});
