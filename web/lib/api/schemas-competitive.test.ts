import { describe, expect, it } from "vitest";
import dashboardFixture from "./__fixtures__/competitive-dashboard.json";
import driftNotSelectedFixture from "./__fixtures__/competitive-drift-notselected.json";
import driftSelectedFixture from "./__fixtures__/competitive-drift-selected.json";
import flowFixture from "./__fixtures__/competitive-flow.json";
import flowEmptyFixture from "./__fixtures__/competitive-flow-empty.json";
import obscurityFixture from "./__fixtures__/competitive-obscurity.json";
import qualityFixture from "./__fixtures__/competitive-quality.json";
import {
  flowApplyResultSchema,
  flowArcSchema,
  listeningDashboardSchema,
  obscuritySchema,
  qualityPlaylistsSchema,
  tasteDriftSchema,
} from "./schemas-competitive";

describe("F1 listening dashboard schema", () => {
  it("parses the live dashboard payload", () => {
    const d = listeningDashboardSchema.parse(dashboardFixture);
    expect(d.range).toBe("all_time");
    expect(d.clock.hours).toHaveLength(24);
    expect(d.clock.weekdays).toHaveLength(7);
    expect(typeof d.minutes.estimated).toBe("boolean");
    expect(d.top_played.length).toBeGreaterThan(0);
  });

  it("accepts an empty-library shape (no plays, null peak)", () => {
    const empty = {
      total_plays: 0,
      distinct_tracks: 0,
      range: "since_crate",
      clock: {
        hours: Array(24).fill(0),
        weekdays: Array(7).fill(0),
        total: 0,
        peak_hour: null,
      },
      minutes: { minutes: 0, estimated: false },
      streaks: { longest: 0, current: 0 },
      top_played: [],
      _links: {},
    };
    expect(listeningDashboardSchema.parse(empty).clock.peak_hour).toBeNull();
  });
});

describe("F3 obscurity schema", () => {
  it("parses the live obscurity payload", () => {
    const o = obscuritySchema.parse(obscurityFixture);
    expect(o.source).toBe("enao_rank");
    expect(o.lastfm_pending).toBe(true);
    expect(o.library.scored_tracks).toBeGreaterThan(0);
    expect(o.playlists.length).toBeGreaterThan(0);
  });

  it("accepts a null library score (nothing scorable)", () => {
    const parsed = obscuritySchema.parse({
      library: { score: null, scored_tracks: 0 },
      playlists: [],
      source: "enao_rank",
      lastfm_pending: true,
      _links: {},
    });
    expect(parsed.library.score).toBeNull();
  });
});

describe("F5 taste drift schema", () => {
  it("parses the timeline-only payload (no snapshot selected)", () => {
    const d = tasteDriftSchema.parse(driftNotSelectedFixture);
    expect(d.comparison).toBeNull();
    expect(d.timeline.length).toBeGreaterThan(0);
    expect(d.timeline.some((t) => t.comparable)).toBe(true);
  });

  it("parses the compared payload (snapshot selected)", () => {
    const d = tasteDriftSchema.parse(driftSelectedFixture);
    expect(d.selected_snapshot_id).not.toBeNull();
    expect(d.comparison).not.toBeNull();
    expect(d.comparison?.axes.length).toBeGreaterThan(0);
    expect(typeof d.comparison?.distance).toBe("number");
    expect(d.comparison?.biggest_mover.feature).toBeTruthy();
  });
});

describe("F6 quality schema", () => {
  it("parses the live quality payload with sub-scores", () => {
    const q = qualityPlaylistsSchema.parse(qualityFixture);
    expect(q.subscore_refs).toEqual([
      "quality_cohesion",
      "quality_uniqueness",
      "quality_freshness",
      "quality_flow",
    ]);
    const first = q.playlists[0];
    expect(first.subscores.length).toBe(4);
    expect(first.subscores[0].ref).toMatch(/^quality_/);
  });
});

describe("F4 flow arc schema", () => {
  it("parses a real preview with a suggested order", () => {
    const f = flowArcSchema.parse(flowFixture);
    expect(f.mood).toBe("rising");
    expect(f.suggested_order.length).toBeGreaterThan(0);
    expect(f.current_flow).not.toBeNull();
    expect(f._links?.apply?.href).toBeTruthy();
  });

  it("parses the below-floor empty preview (no name, null flows)", () => {
    const f = flowArcSchema.parse(flowEmptyFixture);
    expect(f.suggested_order).toEqual([]);
    expect(f.current_flow).toBeNull();
    expect(f.name).toBeUndefined();
  });

  it("parses an apply result", () => {
    const r = flowApplyResultSchema.parse({
      journal_id: 42,
      status: "applied",
      _links: {
        journal: { href: "/v1/journal/42" },
        undo: { href: "/v1/journal/42/undo" },
      },
    });
    expect(r.journal_id).toBe(42);
    expect(r._links?.undo?.href).toBe("/v1/journal/42/undo");
  });
});
