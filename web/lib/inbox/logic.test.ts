import { describe, expect, it } from "vitest";
import {
  type DigestItem,
  digestCollectionSchema,
  digestSchema,
} from "@/lib/api/schemas";
import {
  deepLinkFor,
  groupBySection,
  hasUnread,
  weekLabel,
} from "@/lib/inbox/logic";

function item(overrides: Partial<DigestItem>): DigestItem {
  return {
    id: 1,
    section: "suggestions",
    title: "Gym",
    body: null,
    playlist_id: null,
    candidate_id: null,
    genre: null,
    extra: null,
    ...overrides,
  };
}

describe("inbox logic", () => {
  it("flags unread when any digest lacks read_at", () => {
    expect(hasUnread([{ read_at: null }, { read_at: "2026-07-08" }])).toBe(
      true,
    );
    expect(hasUnread([{ read_at: "2026-07-08" }])).toBe(false);
    expect(hasUnread([])).toBe(false);
  });

  it("groups items into sections in reading order, dropping empties", () => {
    const groups = groupBySection([
      item({ id: 3, section: "frontier", genre: "trip hop" }),
      item({ id: 1, section: "suggestions", playlist_id: 4 }),
      item({ id: 2, section: "suggestions", playlist_id: 5 }),
    ]);
    expect(groups.map((g) => g.section)).toEqual(["suggestions", "frontier"]);
    expect(groups[0].items.map((i) => i.id)).toEqual([1, 2]);
  });

  it("deep-links per section", () => {
    expect(
      deepLinkFor(item({ section: "suggestions", playlist_id: 7 })),
    ).toEqual({ kind: "deck", playlistId: 7 });
    expect(
      deepLinkFor(
        item({ section: "candidates", playlist_id: 7, candidate_id: 9 }),
      ),
    ).toEqual({ kind: "deck", playlistId: 7 });
    expect(deepLinkFor(item({ section: "library", playlist_id: 7 }))).toEqual({
      kind: "playlist",
      playlistId: 7,
    });
    expect(
      deepLinkFor(item({ section: "frontier", genre: "trip hop" })),
    ).toEqual({ kind: "frontier", genre: "trip hop" });
    expect(deepLinkFor(item({ section: "listening" }))).toBeNull();
  });

  it("renders a field-manual week label", () => {
    expect(weekLabel("2026-07-06T00:00:00")).toBe("WEEK OF 06 JUL 2026");
  });
});

describe("phase 10 digest contracts", () => {
  it("parses the digest collection payload shape", () => {
    const payload = {
      items: [
        {
          id: 3,
          week_start: "2026-07-06T00:00:00",
          generated_at: "2026-07-13T05:00:12.345678",
          read_at: null,
          item_count: 5,
          _links: { self: { href: "/v1/digests/3" } },
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
      _links: {
        self: { href: "/v1/digests?limit=20&offset=0" },
        generate: { href: "/v1/digest/generate" },
      },
    };
    expect(digestCollectionSchema.parse(payload).items[0].item_count).toBe(5);
  });

  it("parses the digest detail payload shape", () => {
    const payload = {
      id: 3,
      week_start: "2026-07-06T00:00:00",
      generated_at: "2026-07-13T05:00:12.345678",
      read_at: "2026-07-13T19:30:00",
      items: [
        {
          id: 41,
          section: "candidates",
          title: "Innerbloom — RÜFÜS DU SOL",
          body: "Top of the queue for Gym.",
          playlist_id: 4,
          candidate_id: 92,
          genre: null,
          extra: { fit: 0.8123 },
        },
        {
          id: 42,
          section: "frontier",
          title: "trip hop",
          body: "Moved onto the frontier this week.",
          playlist_id: null,
          candidate_id: null,
          genre: "trip hop",
          extra: { score: 2.31 },
        },
      ],
      _links: {
        self: { href: "/v1/digests/3" },
        read: { href: "/v1/digests/3/read" },
      },
    };
    const parsed = digestSchema.parse(payload);
    expect(parsed.items[1].genre).toBe("trip hop");
  });
});
