/**
 * The canonical set of metric references the UI reaches for an explanation on.
 *
 * This is the checklist side of the explain system: every jargon term and data
 * source called out in the per-surface inventory
 * (thoughts/shared/research/2026-07-17-ux-explainability-insights-research.md §1)
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

/** Triage panel — the newest jargon surface (Phase 2). */
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
  ...SOURCE_REFS,
];

export type MetricRef = (typeof REFERENCED_METRICS)[number];
