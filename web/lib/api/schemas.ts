import { z } from "zod";

/**
 * Zod views of the crate API. Parsing at the query boundary is the
 * schema-drift guard: if the API shape moves, the parse fails loudly instead
 * of propagating undefined through the UI.
 *
 * Live endpoints (api/crate/router/): /v1/playlists, /v1/playlists/{id}/tracks,
 * /v1/sync, /v1/sync/status.
 *
 * Analytics endpoints (graph, playlist analytics, library stats) are the
 * Phase 4 contract — the shapes below are what the web builds against, and
 * the graph fixture parses through the same schema.
 */

export const halLinksSchema = z
  .record(z.string(), z.object({ href: z.string() }))
  .optional();

// ---------------------------------------------------------------- playlists

export const playlistSchema = z.object({
  id: z.number(),
  spotify_id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  snapshot_id: z.string().nullable(),
  is_owned: z.boolean(),
  is_deleted: z.boolean(),
  status: z.string(),
  track_count: z.number(),
  last_synced_at: z.string().nullable(),
  _links: halLinksSchema,
});

export const playlistCollectionSchema = z.object({
  items: z.array(playlistSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  _links: halLinksSchema,
});

export const trackSchema = z.object({
  id: z.number(),
  spotify_id: z.string(),
  isrc: z.string().nullable(),
  name: z.string(),
  artists: z.array(
    z.object({ spotify_id: z.string().optional(), name: z.string() }).loose(),
  ),
  album_name: z.string().nullable(),
  duration_ms: z.number().nullable(),
});

export const playlistTrackSchema = z.object({
  position: z.number(),
  added_at: z.string().nullable(),
  track: trackSchema,
});

export const playlistTrackCollectionSchema = z.object({
  items: z.array(playlistTrackSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  _links: halLinksSchema,
});

// --------------------------------------------------------------------- sync

export const syncStatusSchema = z.object({
  spotify_connected: z.boolean(),
  needs_reauth: z.boolean(),
  playlist_count: z.number(),
  last_synced_at: z.string().nullable(),
  last_event_at: z.string().nullable(),
  _links: halLinksSchema,
});

export const syncResultSchema = z.object({
  playlists_created: z.number(),
  playlists_synced: z.number(),
  playlists_renamed: z.number(),
  playlists_deleted: z.number(),
  playlists_skipped: z.number(),
  tracks_added: z.number(),
  tracks_removed: z.number(),
  _links: halLinksSchema,
});

// ---------------------------------------------------- graph (GET /v1/graph/playlists)

/**
 * Acoustic centroid as library percentiles. Color is computed render-side by
 * lib/color/acoustic.ts — the API ships percentiles, not colors, so the
 * mapping formula lives in exactly one place. Null until enrichment has
 * features for the playlist (renders the grey out-of-gamut state).
 */
export const centroidSchema = z.object({
  acousticness: z.number().min(0).max(1),
  energy: z.number().min(0).max(1),
  valence: z.number().min(0).max(1),
});

export const graphNodeSchema = z.object({
  id: z.number(),
  name: z.string(),
  track_count: z.number(),
  centroid: centroidSchema.nullable(),
});

export const graphEdgeSchema = z.object({
  source: z.number(),
  target: z.number(),
  /** Shared-track count; edge width = 0.75 + 2.25·min(1, shared/40). */
  shared: z.number(),
  /** Containment ≥ 0.95 — rendered dashed with a satellite ring on the subset node. */
  subset: z.boolean(),
});

export const graphResponseSchema = z.object({
  nodes: z.array(graphNodeSchema),
  edges: z.array(graphEdgeSchema),
  /** Feature-enrichment coverage, for the map's coverage indicator. */
  coverage: z.object({
    enriched_tracks: z.number(),
    total_tracks: z.number(),
  }),
  _links: halLinksSchema,
});

// ------------------------------------- playlist analytics (Phase 4 contract)

export const playlistAnalyticsSchema = z.object({
  /** Mean pairwise feature distance in percentile space; null until computed. */
  cohesion: z.number().nullable(),
  /** Top-N Mahalanobis outliers, most distant first. */
  outliers: z.array(
    z.object({
      track_id: z.number(),
      name: z.string(),
      artist: z.string(),
      distance: z.number(),
    }),
  ),
  /** Overlap partners, largest shared count first. */
  overlaps: z.array(
    z.object({
      playlist_id: z.number(),
      name: z.string(),
      shared: z.number(),
      containment: z.number().nullable(),
    }),
  ),
  /** Per-feature library percentiles for the fingerprint bars; null until computed. */
  fingerprint: z
    .array(z.object({ feature: z.string(), percentile: z.number() }))
    .nullable(),
  /** Camelot/BPM flow score for the current ordering; null until computed. */
  flow: z.object({ score: z.number() }).nullable(),
  _links: halLinksSchema,
});

// ------------------------------------------ library stats (Phase 4 contract)

export const libraryStatsSchema = z.object({
  /** Quarterly add-centroid drift, oldest first. */
  drift: z.array(
    z.object({
      quarter: z.string(),
      energy: z.number(),
      valence: z.number(),
      acousticness: z.number(),
    }),
  ),
  /** Cross-library duplicates (same ISRC, possibly different Spotify IDs). */
  duplicates: z.array(
    z.object({
      isrc: z.string().nullable(),
      name: z.string(),
      artist: z.string(),
      playlists: z.array(z.string()),
    }),
  ),
  /** UMAP+HDBSCAN clusters vs playlist assignments; null until computed. */
  clusters: z
    .object({
      ari: z.number(),
      cluster_count: z.number(),
      split_suggestions: z.number(),
      merge_suggestions: z.number(),
    })
    .nullable(),
  _links: halLinksSchema,
});

export type Playlist = z.infer<typeof playlistSchema>;
export type PlaylistCollection = z.infer<typeof playlistCollectionSchema>;
export type PlaylistTrack = z.infer<typeof playlistTrackSchema>;
export type PlaylistTrackCollection = z.infer<
  typeof playlistTrackCollectionSchema
>;
export type SyncStatus = z.infer<typeof syncStatusSchema>;
export type SyncResult = z.infer<typeof syncResultSchema>;
export type AcousticCentroidPayload = z.infer<typeof centroidSchema>;
export type GraphNode = z.infer<typeof graphNodeSchema>;
export type GraphEdge = z.infer<typeof graphEdgeSchema>;
export type GraphResponse = z.infer<typeof graphResponseSchema>;
export type PlaylistAnalytics = z.infer<typeof playlistAnalyticsSchema>;
export type LibraryStats = z.infer<typeof libraryStatsSchema>;
