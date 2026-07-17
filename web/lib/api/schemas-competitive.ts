/**
 * Zod schemas for the competitor-parity surfaces (Phase 6 F-series):
 *   F1 — GET /v1/listening/dashboard   (listening rhythm)
 *   F3 — GET /v1/obscurity             (library + per-playlist obscurity)
 *   F5 — GET /v1/taste/drift           (you vs a past self)
 *   F6 — GET /v1/quality/playlists     (per-playlist quality breakdown)
 *   F4 — GET  /v1/playlists/{id}/flow/arc         (read-only preview)
 *        POST /v1/playlists/{id}/flow/arc/apply    (journaled reorder)
 *
 * Kept in a sibling module to the base survey schemas so the heavier
 * competitor contract stays focused. Every rate/median over an empty table is
 * `null`, matching the backend; the flow preview omits its `name` and nulls its
 * flows below the reorder floor.
 */

import { z } from "zod";
import { halLinksSchema } from "./schemas";

// ── F1 — listening dashboard ─────────────────────────────────────────────────

export const listeningRange = z.enum(["all_time", "since_crate"]);
export type ListeningRange = z.infer<typeof listeningRange>;

const dashboardClockSchema = z.object({
  hours: z.array(z.number()),
  weekdays: z.array(z.number()),
  total: z.number(),
  /** Null when nothing has been played. */
  peak_hour: z.number().nullable(),
});

const dashboardMinutesSchema = z.object({
  minutes: z.number(),
  /** True when any play lacked a recorded length (live captures). */
  estimated: z.boolean(),
});

const dashboardStreaksSchema = z.object({
  longest: z.number(),
  current: z.number(),
});

const dashboardTopPlayedSchema = z.object({
  track_id: z.number(),
  plays: z.number(),
  name: z.string(),
  artist: z.string(),
});

export const listeningDashboardSchema = z.object({
  total_plays: z.number(),
  distinct_tracks: z.number(),
  range: listeningRange,
  clock: dashboardClockSchema,
  minutes: dashboardMinutesSchema,
  streaks: dashboardStreaksSchema,
  top_played: z.array(dashboardTopPlayedSchema),
  _links: halLinksSchema,
});

// ── F3 — obscurity ───────────────────────────────────────────────────────────

const obscurityPlaylistSchema = z.object({
  playlist_id: z.number(),
  name: z.string(),
  /** 0 = mainstream, 1 = niche; null when nothing scorable. */
  score: z.number().nullable(),
  scored_tracks: z.number(),
});

export const obscuritySchema = z.object({
  library: z.object({
    score: z.number().nullable(),
    scored_tracks: z.number(),
  }),
  playlists: z.array(obscurityPlaylistSchema),
  source: z.string(),
  lastfm_pending: z.boolean(),
  _links: halLinksSchema,
});

// ── F5 — taste drift ─────────────────────────────────────────────────────────

const driftTimelineEntrySchema = z.object({
  snapshot_id: z.number(),
  kind: z.string(),
  time_range: z.string(),
  captured_at: z.string(),
  /** Only track readings carry audio, so only they are comparable. */
  comparable: z.boolean(),
});

const driftAxisSchema = z.object({
  feature: z.string(),
  now: z.number(),
  // biome-ignore lint/suspicious/noThenProperty: `then` is the API's field name for the past-self value (now vs then).
  then: z.number(),
  delta: z.number(),
});

const driftComparisonSchema = z.object({
  axes: z.array(driftAxisSchema),
  distance: z.number(),
  biggest_mover: z.object({ feature: z.string(), delta: z.number() }),
});

export const tasteDriftSchema = z.object({
  timeline: z.array(driftTimelineEntrySchema),
  /** Current library fingerprint; null when nothing enriched. */
  now_fingerprint: z.record(z.string(), z.number()).nullable(),
  selected_snapshot_id: z.number().nullable(),
  /** Null unless a snapshot_id was passed. */
  comparison: driftComparisonSchema.nullable(),
  _links: halLinksSchema,
});

// ── F6 — per-playlist quality ────────────────────────────────────────────────

const qualitySubscoreSchema = z.object({
  ref: z.string(),
  label: z.string(),
  value: z.number(),
});

const qualityPlaylistSchema = z.object({
  playlist_id: z.number(),
  name: z.string(),
  track_count: z.number(),
  /** 0..1, higher is better; null when no sub-score could be computed. */
  score: z.number().nullable(),
  subscores: z.array(qualitySubscoreSchema),
});

export const qualityPlaylistsSchema = z.object({
  playlists: z.array(qualityPlaylistSchema),
  subscore_refs: z.array(z.string()),
  _links: halLinksSchema,
});

// ── F4 — flow arc (preview + apply) ──────────────────────────────────────────

export const flowMood = z.enum(["rising", "falling", "peak"]);
export type FlowMood = z.infer<typeof flowMood>;

export const flowArcSchema = z.object({
  playlist_id: z.number(),
  /** Absent from the below-floor empty preview. */
  name: z.string().optional(),
  mood: flowMood,
  suggested_order: z.array(z.number()),
  /** Null below the reorder floor / with nothing reorderable. */
  current_flow: z.number().nullable(),
  suggested_flow: z.number().nullable(),
  adjacent_artist_repeats: z.number(),
  _links: halLinksSchema,
});

export const flowApplyResultSchema = z.object({
  journal_id: z.number(),
  status: z.string(),
  _links: halLinksSchema,
});

// ── inferred types ───────────────────────────────────────────────────────────

export type ListeningDashboard = z.infer<typeof listeningDashboardSchema>;
export type Obscurity = z.infer<typeof obscuritySchema>;
export type ObscurityPlaylist = z.infer<typeof obscurityPlaylistSchema>;
export type TasteDrift = z.infer<typeof tasteDriftSchema>;
export type DriftAxis = z.infer<typeof driftAxisSchema>;
export type DriftComparison = z.infer<typeof driftComparisonSchema>;
export type QualityPlaylists = z.infer<typeof qualityPlaylistsSchema>;
export type QualityPlaylist = z.infer<typeof qualityPlaylistSchema>;
export type FlowArc = z.infer<typeof flowArcSchema>;
export type FlowApplyResult = z.infer<typeof flowApplyResultSchema>;
