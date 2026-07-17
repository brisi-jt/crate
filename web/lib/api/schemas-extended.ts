/**
 * Zod schemas for the extended insights survey (GET /v1/insights/extended) and
 * the pin-candidate pool (GET /v1/insights/pins/candidates).
 *
 * These are the 24 grounded insights mined from the seven previously-untapped
 * tables (play_events, saved_tracks, suggestion_feedback, discovery_candidates,
 * top_items_snapshots, radio_*, mutation_journal, feature_calibrations). Kept in
 * a sibling module to the base survey schemas so the heavier extended contract
 * stays focused.
 *
 * Nullability follows the backend: any per-cent / median / rate over an empty
 * table is `null`, so those fields are `.nullable()`.
 */

import { z } from "zod";
import { halLinksSchema } from "./schemas";

// ── coverage ────────────────────────────────────────────────────────────────

export const extendedCoverageSchema = z.object({
  play_events: z.number(),
  total_saved: z.number(),
  top_snapshots: z.number(),
  /** Plays recorded since crate started (vs imported history). */
  since_crate_plays: z.number(),
});

// ── play_events (I1–I6) ──────────────────────────────────────────────────────

const gapTrackSchema = z.object({
  track_id: z.number(),
  name: z.string(),
  artist: z.string(),
  plays: z.number(),
  memberships: z.number(),
  gap: z.number(),
});

export const playCollectGapSchema = z.object({
  over_played: z.array(gapTrackSchema),
  over_collected: z.array(gapTrackSchema),
  played_tracks: z.number(),
});

export const listeningClockSchema = z.object({
  hours: z.array(z.number()),
  weekdays: z.array(z.number()),
  total: z.number(),
  /** Null when nothing has been played. */
  peak_hour: z.number().nullable(),
});

export const rotationVelocitySchema = z.object({
  total_plays: z.number(),
  recent_plays: z.number(),
  deep_plays: z.number(),
  /** Share of plays landing on recent adds; null with no plays. */
  recency_bias: z.number().nullable(),
});

export const contextMixSchema = z.object({
  total: z.number(),
  contexts: z.array(
    z.object({
      context: z.string(),
      count: z.number(),
      share: z.number(),
    }),
  ),
});

export const playMoodByHourSchema = z.object({
  total: z.number(),
  bands: z.array(
    z.object({
      band: z.string(),
      count: z.number(),
      mean_energy: z.number(),
      mean_valence: z.number(),
    }),
  ),
});

export const deepCutsVsHitsSchema = z.object({
  hit_plays: z.number(),
  deep_cut_plays: z.number(),
  /** Share of listening on obscure tracks; null with no plays. */
  deep_cut_share: z.number().nullable(),
});

export const playEventsSectionSchema = z.object({
  play_collect_gap: playCollectGapSchema,
  listening_clock: listeningClockSchema,
  rotation_velocity: rotationVelocitySchema,
  context_mix: contextMixSchema,
  play_mood_by_hour: playMoodByHourSchema,
  deep_cuts_vs_hits: deepCutsVsHitsSchema,
});

// ── saved_tracks (I7–I10) ────────────────────────────────────────────────────

/** A per-feature (left, right, left−right) row; the value keys vary by axis. */
const fingerprintDeltaAxisSchema = z
  .object({ feature: z.string(), delta: z.number() })
  .catchall(z.number());

export const likedVsPlaylistSchema = z.object({
  axes: z.array(fingerprintDeltaAxisSchema),
  liked_count: z.number(),
  playlist_count: z.number(),
});

export const saveFileLatencySchema = z.object({
  filed_count: z.number(),
  /** Median days from save to first playlist add; null with nothing filed. */
  median_days: z.number().nullable(),
});

export const unsaveChurnSchema = z.object({
  removed: z.number(),
  total_saves: z.number(),
  /** Share of saves later un-liked; null with no saves. */
  churn_rate: z.number().nullable(),
});

export const orphanSavesSchema = z.object({
  orphans: z.array(
    z.object({
      track_id: z.number(),
      name: z.string(),
      artist: z.string(),
    }),
  ),
  saved_count: z.number(),
  orphan_count: z.number(),
});

export const savedSectionSchema = z.object({
  liked_vs_playlist: likedVsPlaylistSchema,
  save_file_latency: saveFileLatencySchema,
  unsave_churn: unsaveChurnSchema,
  orphan_saves: orphanSavesSchema,
  total_saved: z.number(),
});

// ── feedback (I11–I14) ───────────────────────────────────────────────────────

export const sourceEfficacySchema = z.array(
  z.object({
    source: z.string(),
    reviewed: z.number(),
    accept: z.number(),
    reject: z.number(),
    skip: z.number(),
    accept_rate: z.number(),
  }),
);

export const tasteOfYesSchema = z.object({
  axes: z.array(fingerprintDeltaAxisSchema),
  accepted_count: z.number(),
  rejected_count: z.number(),
});

const artistAffinityRowSchema = z.object({
  artist: z.string(),
  accept: z.number(),
  reject: z.number(),
  reviews: z.number(),
  accept_rate: z.number(),
});

export const perArtistAffinitySchema = z.object({
  loved: z.array(artistAffinityRowSchema),
  disliked: z.array(artistAffinityRowSchema),
});

export const candidateFunnelSchema = z.object({
  total: z.number(),
  stages: z.array(z.object({ stage: z.string(), count: z.number() })),
});

export const feedbackSectionSchema = z.object({
  source_efficacy: sourceEfficacySchema,
  taste_of_yes: tasteOfYesSchema,
  per_artist_affinity: perArtistAffinitySchema,
  candidate_funnel: candidateFunnelSchema,
  curation_totals: z.object({
    accept: z.number(),
    reject: z.number(),
    skip: z.number(),
  }),
});

// ── top_items (I15–I17) ──────────────────────────────────────────────────────

export const topVsLibrarySchema = z.object({
  axes: z.array(fingerprintDeltaAxisSchema),
  top_count: z.number(),
  library_count: z.number(),
});

export const affinityChurnSchema = z.object({
  transitions: z.array(z.object({ jaccard: z.number() })),
  /** Mean Jaccard overlap; null with fewer than two snapshots. */
  mean_jaccard: z.number().nullable(),
});

export const shortVsLongSchema = z.object({
  rising: z.array(z.string()),
  fading: z.array(z.string()),
  stable: z.array(z.string()),
  short_count: z.number(),
  long_count: z.number(),
});

export const topItemsSectionSchema = z.object({
  top_vs_library: topVsLibrarySchema,
  affinity_churn: affinityChurnSchema,
  short_vs_long: shortVsLongSchema,
  snapshot_count: z.number(),
});

// ── radio (I18–I19) ──────────────────────────────────────────────────────────

export const radioKeepRateSchema = z.object({
  kept: z.number(),
  skipped: z.number(),
  total: z.number(),
  /** Overall keep rate; null with nothing judged. */
  keep_rate: z.number().nullable(),
  by_seed: z.array(
    z.object({
      seed_kind: z.string(),
      kept: z.number(),
      skipped: z.number(),
      /** Per-seed keep rate; null with nothing judged. */
      keep_rate: z.number().nullable(),
    }),
  ),
});

export const discoveryConversionSchema = z.object({
  discovery_total: z.number(),
  kept: z.number(),
  /** Share of discovery items kept; null with no discovery items. */
  conversion_rate: z.number().nullable(),
});

export const radioSectionSchema = z.object({
  keep_rate: radioKeepRateSchema,
  discovery_conversion: discoveryConversionSchema,
});

// ── journal (I20–I21) ────────────────────────────────────────────────────────

export const curationIntensitySchema = z.object({
  total: z.number(),
  edits_per_week: z.number(),
  undone: z.number(),
  /** Share of edits later undone; null with no edits. */
  undo_rate: z.number().nullable(),
  op_mix: z.array(z.object({ op_type: z.string(), count: z.number() })),
});

export const bulkAlgebraSchema = z.object({
  total: z.number(),
  operations: z.array(z.object({ operation: z.string(), count: z.number() })),
});

export const journalSectionSchema = z.object({
  curation_intensity: curationIntensitySchema,
  bulk_algebra: bulkAlgebraSchema,
});

// ── cross_table (I22–I24) ────────────────────────────────────────────────────

export const listenedVsNeglectedSchema = z.array(
  z.object({
    playlist_id: z.number(),
    name: z.string(),
    months_dormant: z.number(),
    plays: z.number(),
    neglected: z.boolean(),
  }),
);

export const calibrationDriftSchema = z.object({
  features: z.array(
    z.object({
      feature: z.string(),
      points: z.array(
        z.object({ captured_at: z.string(), spread: z.number() }),
      ),
      /** Newest−oldest spread change; null with a single calibration point. */
      spread_delta: z.number().nullable(),
    }),
  ),
});

export const eraAddVsReleaseSchema = z.object({
  total: z.number(),
  add_years: z.array(
    z.object({
      add_year: z.number(),
      count: z.number(),
      median_gap_years: z.number(),
    }),
  ),
});

export const crossTableSectionSchema = z.object({
  listened_vs_neglected: listenedVsNeglectedSchema,
  calibration_drift: calibrationDriftSchema,
  era_add_vs_release: eraAddVsReleaseSchema,
});

// ── the whole payload ────────────────────────────────────────────────────────

export const extendedInsightsSchema = z.object({
  coverage: extendedCoverageSchema,
  play_events: playEventsSectionSchema,
  saved: savedSectionSchema,
  feedback: feedbackSectionSchema,
  top_items: topItemsSectionSchema,
  radio: radioSectionSchema,
  journal: journalSectionSchema,
  cross_table: crossTableSectionSchema,
  _links: halLinksSchema,
});

// ── pin candidates ───────────────────────────────────────────────────────────

export const pinCandidateSchema = z.object({
  family: z.string(),
  category: z.string(),
  metric_ref: z.string(),
  anchor: z.string(),
  line: z.string(),
  dismissible_id: z.string(),
  salience: z.number(),
});

export const pinCandidatesSchema = z.object({
  surface: z.string(),
  candidates: z.array(pinCandidateSchema),
  _links: halLinksSchema,
});

// ── inferred types ───────────────────────────────────────────────────────────

export type ExtendedCoverage = z.infer<typeof extendedCoverageSchema>;
export type PlayEventsSection = z.infer<typeof playEventsSectionSchema>;
export type PlayCollectGap = z.infer<typeof playCollectGapSchema>;
export type ListeningClock = z.infer<typeof listeningClockSchema>;
export type RotationVelocity = z.infer<typeof rotationVelocitySchema>;
export type ContextMix = z.infer<typeof contextMixSchema>;
export type PlayMoodByHour = z.infer<typeof playMoodByHourSchema>;
export type DeepCutsVsHits = z.infer<typeof deepCutsVsHitsSchema>;
export type SavedSection = z.infer<typeof savedSectionSchema>;
export type LikedVsPlaylist = z.infer<typeof likedVsPlaylistSchema>;
export type SaveFileLatency = z.infer<typeof saveFileLatencySchema>;
export type UnsaveChurn = z.infer<typeof unsaveChurnSchema>;
export type OrphanSaves = z.infer<typeof orphanSavesSchema>;
export type FeedbackSection = z.infer<typeof feedbackSectionSchema>;
export type SourceEfficacy = z.infer<typeof sourceEfficacySchema>;
export type TasteOfYes = z.infer<typeof tasteOfYesSchema>;
export type PerArtistAffinity = z.infer<typeof perArtistAffinitySchema>;
export type CandidateFunnel = z.infer<typeof candidateFunnelSchema>;
export type TopItemsSection = z.infer<typeof topItemsSectionSchema>;
export type TopVsLibrary = z.infer<typeof topVsLibrarySchema>;
export type AffinityChurn = z.infer<typeof affinityChurnSchema>;
export type ShortVsLong = z.infer<typeof shortVsLongSchema>;
export type RadioSection = z.infer<typeof radioSectionSchema>;
export type RadioKeepRate = z.infer<typeof radioKeepRateSchema>;
export type DiscoveryConversion = z.infer<typeof discoveryConversionSchema>;
export type JournalSection = z.infer<typeof journalSectionSchema>;
export type CurationIntensity = z.infer<typeof curationIntensitySchema>;
export type BulkAlgebra = z.infer<typeof bulkAlgebraSchema>;
export type CrossTableSection = z.infer<typeof crossTableSectionSchema>;
export type ListenedVsNeglected = z.infer<typeof listenedVsNeglectedSchema>;
export type CalibrationDrift = z.infer<typeof calibrationDriftSchema>;
export type EraAddVsRelease = z.infer<typeof eraAddVsReleaseSchema>;
export type ExtendedInsights = z.infer<typeof extendedInsightsSchema>;
export type PinCandidate = z.infer<typeof pinCandidateSchema>;
export type PinCandidates = z.infer<typeof pinCandidatesSchema>;
