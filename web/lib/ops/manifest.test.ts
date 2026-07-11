import { describe, expect, it } from "vitest";
import { manifestSchema } from "@/lib/api/schemas";
import {
  commitIsDestructive,
  commitLabel,
  manifestIsEmpty,
  manifestRows,
} from "./manifest";

const mixed = manifestSchema.parse({
  entries: [
    {
      playlist_id: 7,
      playlist_name: "Peak Hours",
      new: false,
      adds: [
        { track_id: 1, spotify_id: "ta", name: "Hyperdrive", artist: "KREAM" },
        { track_id: 2, spotify_id: "tb", name: "Rumble", artist: "Skrillex" },
      ],
      removes: [
        {
          track_id: 3,
          spotify_id: "tc",
          name: "Sprinter",
          artist: "Dave",
          position: 4,
        },
      ],
    },
    {
      playlist_id: null,
      playlist_name: "New Comp",
      new: true,
      adds: [
        { track_id: 4, spotify_id: "td", name: "Holocene", artist: "Bon Iver" },
      ],
      removes: [],
    },
  ],
  summary: { adds: 3, removes: 1, playlists: 2 },
});

describe("manifest rows", () => {
  it("flattens entries in order, adds before removes", () => {
    const rows = manifestRows(mixed);
    expect(rows.map((r) => [r.playlist, r.delta, r.title])).toEqual([
      ["Peak Hours", "add", "Hyperdrive"],
      ["Peak Hours", "add", "Rumble"],
      ["Peak Hours", "remove", "Sprinter"],
      ["New Comp", "add", "Holocene"],
    ]);
  });

  it("carries positions only for removals", () => {
    const rows = manifestRows(mixed);
    expect(rows[0].position).toBeNull();
    expect(rows[2].position).toBe(4);
  });

  it("gives every row a distinct key", () => {
    const keys = manifestRows(mixed).map((r) => r.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("commit copy", () => {
  it("shows removes then adds", () => {
    expect(commitLabel(mixed)).toBe("COMMIT −1 / +3");
  });

  it("add-only ops show adds alone and are not destructive", () => {
    const addsOnly = {
      ...mixed,
      summary: { adds: 5, removes: 0, playlists: 1 },
    };
    expect(commitLabel(addsOnly)).toBe("COMMIT +5");
    expect(commitIsDestructive(addsOnly)).toBe(false);
  });

  it("removals mark the commit destructive", () => {
    expect(commitIsDestructive(mixed)).toBe(true);
  });

  it("detects an empty delta", () => {
    const empty = { ...mixed, summary: { adds: 0, removes: 0, playlists: 1 } };
    expect(manifestIsEmpty(empty)).toBe(true);
    expect(manifestIsEmpty(mixed)).toBe(false);
  });
});
