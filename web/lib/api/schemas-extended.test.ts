import { describe, expect, it } from "vitest";
import {
  extendedInsightsSchema,
  pinCandidatesSchema,
} from "./schemas-extended";

/**
 * A representative extended-insights payload shaped exactly like the live
 * GET /v1/insights/extended body (captured against a real library). This is the
 * contract: the schema must parse it, and must tolerate the nullable numeric
 * fields (rates/medians that are null on an empty table).
 */
const EXTENDED_FIXTURE = {
  coverage: {
    play_events: 199,
    total_saved: 2083,
    top_snapshots: 18,
    since_crate_plays: 199,
  },
  play_events: {
    context_mix: {
      total: 199,
      contexts: [{ context: "playlist", count: 124, share: 0.6231 }],
    },
    listening_clock: {
      hours: new Array(24).fill(0),
      total: 199,
      weekdays: new Array(7).fill(0),
      peak_hour: 11,
    },
    play_collect_gap: {
      over_played: [
        {
          gap: 2,
          name: "The Kill",
          plays: 3,
          artist: "Thirty Seconds To Mars",
          track_id: 260,
          memberships: 1,
        },
      ],
      played_tracks: 120,
      over_collected: [],
    },
    deep_cuts_vs_hits: {
      hit_plays: 12,
      deep_cut_plays: 187,
      deep_cut_share: 0.9397,
    },
    play_mood_by_hour: {
      bands: [
        {
          band: "morning",
          count: 40,
          mean_energy: 0.5,
          mean_valence: 0.5,
        },
      ],
      total: 199,
    },
    rotation_velocity: {
      deep_plays: 175,
      total_plays: 199,
      recency_bias: 0.12,
      recent_plays: 24,
    },
  },
  saved: {
    total_saved: 2083,
    orphan_saves: {
      orphans: [{ name: "X", artist: "Y", track_id: 5 }],
      saved_count: 2083,
      orphan_count: 1095,
    },
    unsave_churn: { removed: 0, churn_rate: 0.0, total_saves: 2083 },
    liked_vs_playlist: {
      axes: [
        {
          delta: 0.1,
          liked: 0.6,
          feature: "energy",
          playlist: 0.5,
        },
      ],
      liked_count: 2083,
      playlist_count: 5000,
    },
    save_file_latency: { filed_count: 900, median_days: 4.5 },
  },
  feedback: {
    taste_of_yes: { axes: [], accepted_count: 0, rejected_count: 0 },
    curation_totals: { skip: 0, accept: 0, reject: 0 },
    source_efficacy: [
      {
        skip: 1,
        accept: 4,
        reject: 2,
        source: "reccobeats",
        reviewed: 6,
        accept_rate: 0.6667,
      },
    ],
    candidate_funnel: {
      total: 10,
      stages: [{ count: 3, stage: "pending" }],
    },
    per_artist_affinity: { loved: [], disliked: [] },
  },
  top_items: {
    short_vs_long: {
      fading: ["a", "b"],
      rising: ["c"],
      stable: [],
      long_count: 50,
      short_count: 30,
    },
    affinity_churn: {
      transitions: [{ jaccard: 0.5 }],
      mean_jaccard: 0.5,
    },
    snapshot_count: 18,
    top_vs_library: {
      axes: [
        {
          top: 0.6,
          delta: 0.1,
          feature: "energy",
          library: 0.5,
        },
      ],
      top_count: 50,
      library_count: 5000,
    },
  },
  radio: {
    keep_rate: {
      kept: 8,
      total: 10,
      by_seed: [
        {
          kept: 8,
          skipped: 2,
          keep_rate: 0.8,
          seed_kind: "playlist",
        },
      ],
      skipped: 2,
      keep_rate: 0.8,
    },
    discovery_conversion: {
      kept: 3,
      conversion_rate: 0.6,
      discovery_total: 5,
    },
  },
  journal: {
    bulk_algebra: {
      total: 4,
      operations: [{ count: 4, operation: "union" }],
    },
    curation_intensity: {
      total: 20,
      op_mix: [{ count: 12, op_type: "add" }],
      undone: 1,
      undo_rate: 0.05,
      edits_per_week: 3.2,
    },
  },
  cross_table: {
    calibration_drift: {
      features: [
        {
          points: [{ spread: 0.4, captured_at: "2026-07-01T00:00:00" }],
          feature: "energy",
          spread_delta: 0.0,
        },
      ],
    },
    era_add_vs_release: {
      total: 100,
      add_years: [{ count: 12, add_year: 2015, median_gap_years: 3.0 }],
    },
    listened_vs_neglected: [
      {
        name: "Deep Focus",
        plays: 40,
        neglected: false,
        playlist_id: 12,
        months_dormant: 2,
      },
    ],
  },
  _links: {
    self: { href: "/v1/insights/extended" },
    insights: { href: "/v1/insights" },
    candidates: { href: "/v1/insights/pins/candidates?surface=insights" },
  },
};

describe("extendedInsightsSchema", () => {
  it("parses a full live-shaped payload", () => {
    const parsed = extendedInsightsSchema.parse(EXTENDED_FIXTURE);
    expect(parsed.coverage.play_events).toBe(199);
    expect(parsed.play_events.listening_clock.peak_hour).toBe(11);
    expect(parsed.saved.orphan_saves.orphan_count).toBe(1095);
    expect(parsed.cross_table.era_add_vs_release.add_years[0].add_year).toBe(
      2015,
    );
  });

  it("tolerates null rate/median fields (empty tables)", () => {
    const empty = structuredClone(EXTENDED_FIXTURE);
    empty.play_events.listening_clock.peak_hour = null as unknown as number;
    empty.play_events.rotation_velocity.recency_bias =
      null as unknown as number;
    empty.play_events.deep_cuts_vs_hits.deep_cut_share =
      null as unknown as number;
    empty.saved.unsave_churn.churn_rate = null as unknown as number;
    empty.saved.save_file_latency.median_days = null as unknown as number;
    empty.radio.keep_rate.keep_rate = null as unknown as number;
    empty.radio.keep_rate.by_seed[0].keep_rate = null as unknown as number;
    empty.radio.discovery_conversion.conversion_rate =
      null as unknown as number;
    empty.journal.curation_intensity.undo_rate = null as unknown as number;
    empty.top_items.affinity_churn.mean_jaccard = null as unknown as number;
    empty.cross_table.calibration_drift.features[0].spread_delta =
      null as unknown as number;
    const parsed = extendedInsightsSchema.parse(empty);
    expect(parsed.play_events.listening_clock.peak_hour).toBeNull();
    expect(parsed.saved.save_file_latency.median_days).toBeNull();
  });

  it("parses a zeroed empty-library payload shape", () => {
    const zeroed = structuredClone(EXTENDED_FIXTURE);
    zeroed.coverage.play_events = 0;
    zeroed.play_events.context_mix.contexts = [];
    zeroed.play_events.play_collect_gap.over_played = [];
    zeroed.saved.orphan_saves.orphans = [];
    zeroed.saved.liked_vs_playlist.axes = [];
    zeroed.top_items.top_vs_library.axes = [];
    zeroed.cross_table.listened_vs_neglected = [];
    zeroed.cross_table.calibration_drift.features = [];
    expect(() => extendedInsightsSchema.parse(zeroed)).not.toThrow();
  });
});

describe("pinCandidatesSchema", () => {
  it("parses the candidate pool response", () => {
    const parsed = pinCandidatesSchema.parse({
      surface: "insights",
      candidates: [
        {
          family: "play_events",
          category: "play_events",
          metric_ref: "play_collect_gap",
          anchor: "over_played:260",
          line: "You spin The Kill far more than you've filed it.",
          dismissible_id:
            "insights:play_events:over_played:260:play_collect_gap",
          salience: 0.12,
        },
      ],
      _links: {
        self: { href: "/v1/insights/pins/candidates?surface=insights" },
        extended: { href: "/v1/insights/extended" },
        insights: { href: "/v1/insights" },
      },
    });
    expect(parsed.candidates).toHaveLength(1);
    expect(parsed.candidates[0].family).toBe("play_events");
  });

  it("parses an empty candidate pool", () => {
    const parsed = pinCandidatesSchema.parse({
      surface: "insights",
      candidates: [],
      _links: {
        self: { href: "/v1/insights/pins/candidates?surface=insights" },
        extended: { href: "/v1/insights/extended" },
        insights: { href: "/v1/insights" },
      },
    });
    expect(parsed.candidates).toEqual([]);
  });
});
