/**
 * The canonical set of metric references the UI reaches for an explanation on.
 *
 * This is the checklist side of the explain system: every jargon term and data
 * source called out in the per-surface inventory
 * lives here as a stable key. The glossary (glossary.ts) must resolve every one
 * of these, and must not carry orphan entries that nothing references.
 *
 * Grouped by surface only for readability; the values are a flat namespace.
 */

/** Playlist graph canvas + hover card. */
export const GRAPH_REFS = [
  "acoustic_color",
  "node_size",
  "edge_width",
  "orbit_ring",
  "top_overlap",
  "features_coverage",
] as const;

/** Track field canvas. */
export const FIELD_REFS = ["umap", "cluster_id", "noise", "ari"] as const;

/** Artist galaxy canvas. */
export const GALAXY_REFS = [
  "bridging_artists",
  "co_curated_edge",
  "similarity_edge",
  "artist_reach",
] as const;

/** Listening deck + fingerprint bars. */
export const DECK_REFS = ["percentile", "profile_tick"] as const;

/** Frontier explorer. */
export const FRONTIER_REFS = [
  "territory",
  "frontier",
  "presence",
  "atlas",
  "matched_artists",
] as const;

/** Radio panel. */
export const RADIO_REFS = ["harmonic_flow", "discovery_ratio"] as const;

/** Ops log panel. */
export const OPS_LOG_REFS = ["op_status", "dedupe"] as const;

/** Insights page — taste identity. */
export const IDENTITY_REFS = [
  "genre_entropy",
  "effective_genres",
  "gs_score",
  "mean_rarity",
  "fingerprint",
  "archetype_axes",
] as const;

/** Insights page — sonic signatures. */
export const SONIC_REFS = [
  "camelot",
  "mood_quadrants",
  "tempo_spine",
  "ridgelines",
] as const;

/** Insights page — archaeology + era + territory. */
export const ARCHAEOLOGY_REFS = [
  "core_sample",
  "dormancy",
  "center_of_gravity",
  "taste_freeze",
] as const;

/** Library stats + bulk ops chrome. */
export const STATS_REFS = ["split_merge_hints", "calibration_drift"] as const;

/** Triage panel jargon surface. */
export const TRIAGE_REFS = [
  "triage_source",
  "orphan_filter",
  "sonic_fit",
  "artist_overlap",
  "placement_history",
  "vibe_match",
  "suggestion_rank",
  "cluster_proposal",
] as const;

/**
 * Insights page — the extended survey (24 insights over the deep tables).
 * `calibration_drift` is intentionally absent here: it already lives in
 * STATS_REFS and resolves to the same glossary entry (the survey renders the
 * per-feature spread; the stats surface names the drift). Listing it twice
 * would trip the no-duplicate-refs gate.
 */
export const EXTENDED_INSIGHT_REFS = [
  // play_events (I1–I6)
  "play_collect_gap",
  "listening_clock",
  "rotation_velocity",
  "context_mix",
  "play_mood_by_hour",
  "deep_cuts_vs_hits",
  // saved_tracks (I7–I10)
  "liked_vs_playlist",
  "save_file_latency",
  "unsave_churn",
  "orphan_saves",
  // feedback (I11–I14)
  "source_efficacy",
  "taste_of_yes",
  "per_artist_affinity",
  "candidate_funnel",
  // top_items (I15–I17)
  "top_vs_library",
  "affinity_churn",
  "short_vs_long",
  // radio (I18–I19)
  "radio_keep_rate",
  "discovery_conversion",
  // journal (I20–I21)
  "curation_intensity",
  "bulk_algebra",
  // cross-table (I22, I24 — I23 calibration_drift reuses STATS_REFS)
  "listened_vs_neglected",
  "era_add_vs_release",
] as const;

/**
 * Competitor-parity surfaces — the listening dashboard, obscurity, taste drift,
 * flow sequencer, and per-playlist quality. `listening_clock` is intentionally
 * absent: the dashboard reuses the same clock the extended survey already
 * explains, resolving to that one entry (listing it twice would trip the
 * no-duplicate-refs gate).
 */
export const COMPETITIVE_REFS = [
  // listening dashboard (F1)
  "listening_rhythm",
  "listening_minutes",
  "listening_streaks",
  "listening_clock_peak",
  // obscurity (F3)
  "obscurity_library",
  "obscurity_playlist",
  // taste drift (F5)
  "taste_drift",
  // flow sequencer (F4)
  "flow_arc",
  // per-playlist quality (F6) — the four payload-emitted sub-score refs
  "quality_cohesion",
  "quality_uniqueness",
  "quality_freshness",
  "quality_flow",
] as const;

/** Data providers — every source string the app never surfaces in-UI today. */
export const SOURCE_REFS = [
  "source_reccobeats",
  "source_lastfm",
  "source_musicbrainz",
  "source_deezer",
  "source_enao",
  "source_essentia",
] as const;

/**
 * The flat, de-duplicated checklist. Every referenced key the UI can pass to
 * <Explain metric={…}> must appear here, and every one here must resolve in the
 * glossary.
 */
export const REFERENCED_METRICS: readonly string[] = [
  ...GRAPH_REFS,
  ...FIELD_REFS,
  ...GALAXY_REFS,
  ...DECK_REFS,
  ...FRONTIER_REFS,
  ...RADIO_REFS,
  ...OPS_LOG_REFS,
  ...IDENTITY_REFS,
  ...SONIC_REFS,
  ...ARCHAEOLOGY_REFS,
  ...STATS_REFS,
  ...TRIAGE_REFS,
  ...EXTENDED_INSIGHT_REFS,
  ...COMPETITIVE_REFS,
  ...SOURCE_REFS,
];

export type MetricRef = (typeof REFERENCED_METRICS)[number];
