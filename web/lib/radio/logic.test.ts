import { describe, expect, it } from "vitest";
import { type RadioItem, radioSessionSchema } from "@/lib/api/schemas";
import {
  itemReadout,
  nextPlayableIndex,
  sessionComplete,
  sessionSummary,
} from "@/lib/radio/logic";

function item(overrides: Partial<RadioItem>): RadioItem {
  return {
    id: 1,
    position: 0,
    kind: "library",
    track_id: 10,
    candidate_id: null,
    title: "Track",
    artist: "Artist",
    spotify_id: null,
    preview_url: null,
    tempo: null,
    camelot: null,
    feedback: null,
    journal_id: null,
    _links: undefined,
    ...overrides,
  };
}

describe("radio logic", () => {
  it("finds the next playable item forward only", () => {
    const items = [
      item({ id: 1, preview_url: null }),
      item({ id: 2, preview_url: "https://p/2.mp3" }),
      item({ id: 3, preview_url: null }),
      item({ id: 4, preview_url: "https://p/4.mp3" }),
    ];
    expect(nextPlayableIndex(items, 0)).toBe(1);
    expect(nextPlayableIndex(items, 2)).toBe(3);
    expect(nextPlayableIndex(items, 4)).toBeNull();
  });

  it("recomputes the summary from item state", () => {
    const items = [
      item({ id: 1, feedback: "kept", journal_id: 7 }),
      item({ id: 2, feedback: "kept" }),
      item({ id: 3, feedback: "skipped" }),
      item({ id: 4 }),
    ];
    expect(sessionSummary(items)).toEqual({
      kept: 2,
      skipped: 1,
      added: 1,
      pending: 1,
    });
    expect(sessionComplete(items)).toBe(false);
    expect(sessionComplete(items.slice(0, 3))).toBe(true);
    expect(sessionComplete([])).toBe(false);
  });

  it("formats the transition readout from what is known", () => {
    expect(itemReadout(item({ tempo: 127.6, camelot: "8A" }))).toBe(
      "128 BPM · 8A",
    );
    expect(itemReadout(item({ tempo: 94.2 }))).toBe("94 BPM");
    expect(itemReadout(item({}))).toBeNull();
  });
});

describe("phase 10 radio contract", () => {
  it("parses the radio session payload shape", () => {
    const payload = {
      id: 5,
      seed_kind: "playlist",
      seed_playlist_id: 4,
      seed_genre: null,
      label: "Gym",
      discovery_ratio: 0.2,
      items: [
        {
          id: 51,
          position: 0,
          kind: "library",
          track_id: 10,
          candidate_id: null,
          title: "Opus",
          artist: "Eric Prydz",
          spotify_id: "6rqhFgbbKwnb9MLmUQDhG6",
          preview_url: "https://cdnt-preview.dzcdn.net/api/1/x.mp3",
          tempo: 126.0,
          camelot: "8A",
          feedback: null,
          journal_id: null,
          _links: {
            feedback: { href: "/v1/radio/5/items/51/feedback" },
            spotify: {
              href: "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6",
            },
          },
        },
        {
          id: 52,
          position: 1,
          kind: "discovery",
          track_id: null,
          candidate_id: 92,
          title: "Hyperwave",
          artist: "Cassian",
          spotify_id: null,
          preview_url: null,
          tempo: null,
          camelot: null,
          feedback: "kept",
          journal_id: 12,
          _links: {
            feedback: { href: "/v1/radio/5/items/52/feedback" },
            undo: { href: "/v1/journal/12/undo" },
          },
        },
      ],
      summary: { kept: 1, skipped: 0, added: 1, pending: 1 },
      _links: {
        self: { href: "/v1/radio/5" },
        playlist: { href: "/v1/playlists/4" },
      },
    };
    const parsed = radioSessionSchema.parse(payload);
    expect(parsed.items[1].journal_id).toBe(12);
    expect(parsed.summary.pending).toBe(1);
  });
});
