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
  /** Spotify playlist cover, when set; the hover card builds a member mosaic otherwise. */
  image_url: z.string().nullable().optional(),
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

// -------------------------------------- artist galaxy (GET /v1/graph/artists)

/**
 * One artist across the in-scope playlists. `id` is the stable artist key
 * (lowercase name) — edges reference it, and the artist card panel keys off
 * it. The node is self-sufficient: everything the card shows travels here.
 */
export const galaxyNodeSchema = z.object({
  id: z.string(),
  name: z.string(),
  /** Distinct library tracks crediting the artist — drives sqrt node sizing. */
  track_count: z.number(),
  playlist_count: z.number(),
  playlist_ids: z.array(z.number()),
  /** Mean sound of the artist's enriched tracks; null renders the grey state. */
  centroid: centroidSchema.nullable(),
  /** Small artist photo for the galaxy hover card; null until backfill reaches them. */
  image_url: z.string().nullable().optional(),
  genres: z.array(z.string()),
  /** Library tracks, alphabetical, capped server-side (track_count = full total). */
  tracks: z.array(z.object({ id: z.number(), name: z.string() })),
  similar: z.array(
    z.object({ name: z.string(), weight: z.number(), in_library: z.boolean() }),
  ),
});

export const galaxyEdgeSchema = z.object({
  source: z.string(),
  target: z.string(),
  /** co_playlist = solid (weight = shared playlists); similarity = dashed (0..1). */
  kind: z.enum(["co_playlist", "similarity"]),
  weight: z.number(),
});

export const artistGalaxyResponseSchema = z.object({
  nodes: z.array(galaxyNodeSchema),
  edges: z.array(galaxyEdgeSchema),
  /** Cap honesty: large libraries show only the most connected artists. */
  coverage: z.object({
    artists_total: z.number(),
    artists_shown: z.number(),
    edges_total: z.number(),
    edges_shown: z.number(),
  }),
  _links: halLinksSchema,
});

// -------------------------------- frontier (GET /v1/discovery/frontier)

export const territoryGenreSchema = z.object({
  genre_id: z.number(),
  name: z.string(),
  enao_rank: z.number().nullable(),
  /** Library hold on the genre relative to its strongest genre, 0..1. */
  presence: z.number(),
  matched_artists: z.number(),
});

export const frontierGenreSchema = z.object({
  genre_id: z.number(),
  name: z.string(),
  enao_rank: z.number().nullable(),
  /** Adjacency to territory, discounted by existing presence. */
  score: z.number(),
  presence: z.number(),
  adjacent_to: z.array(z.string()),
  /** Defining artists NOT in the library — the discovery seeds. */
  exemplars: z.array(z.object({ name: z.string(), weight: z.number() })),
});

export const frontierResponseSchema = z.object({
  territory: z.array(territoryGenreSchema),
  frontier: z.array(frontierGenreSchema),
  coverage: z.object({
    library_artists: z.number(),
    matched_artists: z.number(),
  }),
  _links: halLinksSchema,
});

// ------------------------------------------- track map (GET /v1/map/tracks)

/**
 * One enriched track projected onto the 2D sound field. `features` and
 * `playlist_ids` are optional: the API doesn't ship them yet, so the web
 * derives color and membership client-side (lib/field) — when the payload
 * grows them, the render path picks them up without a schema change.
 */
export const mapPointSchema = z.object({
  track_id: z.number(),
  name: z.string(),
  artist: z.string(),
  x: z.number(),
  y: z.number(),
  /** Density cluster label; -1 = noise (no cluster). */
  cluster: z.number(),
  /** Small album-art thumb for the hover card; null until the album is imaged. */
  album_image_url: z.string().nullable().optional(),
  /** Per-track library percentiles — drives exact acoustic color when present. */
  features: centroidSchema.nullable().optional(),
  /** Owning playlists — replaces the client-side membership join when present. */
  playlist_ids: z.array(z.number()).optional(),
});

export const trackMapResponseSchema = z.object({
  points: z.array(mapPointSchema),
  cluster_count: z.number(),
  noise_count: z.number(),
  /** Adjusted Rand index vs playlist grouping; null until computable. */
  ari: z.number().nullable(),
  split_suggestions: z.array(
    z.object({
      playlist_id: z.number(),
      name: z.string(),
      clusters: z.array(z.object({ cluster: z.number(), share: z.number() })),
    }),
  ),
  merge_suggestions: z.array(
    z.object({
      cluster: z.number(),
      playlist_ids: z.array(z.number()),
      playlist_names: z.array(z.string()),
    }),
  ),
  /** Layout fingerprint — identical library state reproduces it exactly. */
  layout_hash: z.string().nullable(),
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

// -------------------------------------------------- writes (Phase 7 live)

/** Result of a single journaled write (add/remove/rename/reorder). */
export const mutationResultSchema = z.object({
  journal_id: z.number(),
  status: z.string(),
  playlist_id: z.number(),
  track_count: z.number(),
  _links: halLinksSchema,
});

export const manifestTrackRefSchema = z.object({
  track_id: z.number(),
  spotify_id: z.string(),
  name: z.string(),
  artist: z.string(),
});

export const manifestRemoveRefSchema = manifestTrackRefSchema.extend({
  position: z.number(),
});

export const manifestEntrySchema = z.object({
  playlist_id: z.number().nullable(),
  playlist_name: z.string(),
  /** True when apply will create this playlist. */
  new: z.boolean(),
  adds: z.array(manifestTrackRefSchema),
  removes: z.array(manifestRemoveRefSchema),
});

export const manifestSchema = z.object({
  entries: z.array(manifestEntrySchema),
  summary: z.object({
    adds: z.number(),
    removes: z.number(),
    playlists: z.number(),
  }),
});

/** A stored dry run: apply performs exactly this delta or 409s. */
export const opPreviewSchema = z.object({
  preview_id: z.number(),
  operation: z.string(),
  manifest: manifestSchema,
  created_at: z.string(),
  _links: halLinksSchema,
});

export const applyResultSchema = z.object({
  journal_id: z.number(),
  status: z.string(),
  results: z.array(
    z.object({
      playlist_id: z.number().nullable(),
      name: z.string(),
      status: z.string(),
      error: z.string().nullable().optional(),
    }),
  ),
  _links: halLinksSchema,
});

export const journalEntrySchema = z.object({
  id: z.number(),
  op_type: z.string(),
  status: z.string(),
  summary: z.string(),
  created_at: z.string(),
  undone_at: z.string().nullable(),
  detail: z.record(z.string(), z.unknown()),
  _links: halLinksSchema,
});

export const journalCollectionSchema = z.object({
  items: z.array(journalEntrySchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  _links: halLinksSchema,
});

export const undoResultSchema = z.object({
  journal_id: z.number(),
  status: z.string(),
  _links: halLinksSchema,
});

// ------------------------------------------------- discovery (Phase 8 live)

/** How a suggestion's fit score decomposes — the deck's readout. */
export const fitBreakdownSchema = z.object({
  proximity: z.number(),
  affinity: z.number(),
  novelty: z.number(),
  feedback: z.number(),
  fit: z.number(),
});

/** One feature compared between the candidate and the playlist (percentiles). */
export const fingerprintPointSchema = z.object({
  feature: z.string(),
  candidate: z.number(),
  playlist: z.number(),
});

export const suggestionSchema = z.object({
  id: z.number(),
  title: z.string(),
  artist: z.string(),
  album_name: z.string().nullable(),
  duration_ms: z.number().nullable(),
  source: z.string(),
  seed_artist: z.string().nullable(),
  spotify_id: z.string().nullable(),
  /** 30s audio; null = no preview found (deck offers the Spotify link). */
  preview_url: z.string().nullable(),
  fit: z.number(),
  breakdown: fitBreakdownSchema,
  fingerprint: z.array(fingerprintPointSchema),
  _links: halLinksSchema,
});

export const suggestionQueueSchema = z.object({
  playlist_id: z.number(),
  playlist_name: z.string(),
  total: z.number(),
  items: z.array(suggestionSchema),
  _links: halLinksSchema,
});

export const feedbackResultSchema = z.object({
  candidate_id: z.number(),
  action: z.string(),
  status: z.string(),
  /** Set on accept: the journal entry for the playlist add (undo target). */
  journal_id: z.number().nullable(),
  mutation_status: z.string().nullable(),
  _links: halLinksSchema,
});

export const discoveryRunResultSchema = z.object({
  playlists_processed: z.number(),
  generated_lastfm: z.number(),
  generated_reccobeats: z.number(),
  /** Candidates sourced from a genre seed's exemplar artists. */
  generated_enao: z.number().optional(),
  excluded: z.number(),
  resolved: z.number(),
  unresolvable: z.number(),
  features_fetched: z.number(),
  previews_resolved: z.number(),
  lastfm_skipped: z.boolean(),
  /** Per-step failures the pass survived (source outages skip, never abort). */
  errors: z.array(z.string()).optional(),
  _links: halLinksSchema,
});

// ------------------------------------------------- digests (Phase 10 inbox)

export const digestSectionSchema = z.enum([
  "suggestions",
  "candidates",
  "library",
  "listening",
  "frontier",
]);

export const digestItemSchema = z.object({
  id: z.number(),
  section: digestSectionSchema,
  title: z.string(),
  body: z.string().nullable(),
  playlist_id: z.number().nullable(),
  candidate_id: z.number().nullable(),
  genre: z.string().nullable(),
  /** Section-specific readouts: counts, fit scores, play totals. */
  extra: z.record(z.string(), z.unknown()).nullable(),
});

export const digestSchema = z.object({
  id: z.number(),
  week_start: z.string(),
  generated_at: z.string(),
  /** Null until the digest has been opened — the inbox unread cue. */
  read_at: z.string().nullable(),
  items: z.array(digestItemSchema),
  _links: halLinksSchema,
});

export const digestSummarySchema = z.object({
  id: z.number(),
  week_start: z.string(),
  generated_at: z.string(),
  read_at: z.string().nullable(),
  item_count: z.number(),
  _links: halLinksSchema,
});

export const digestCollectionSchema = z.object({
  items: z.array(digestSummarySchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  _links: halLinksSchema,
});

// --------------------------------------------------- radio (Phase 10 live)

export const radioItemSchema = z.object({
  id: z.number(),
  position: z.number(),
  kind: z.enum(["library", "discovery"]),
  track_id: z.number().nullable(),
  candidate_id: z.number().nullable(),
  title: z.string(),
  artist: z.string(),
  spotify_id: z.string().nullable(),
  preview_url: z.string().nullable(),
  /** BPM readout, when known. */
  tempo: z.number().nullable(),
  /** Camelot wheel position ("8A"), when known. */
  camelot: z.string().nullable(),
  feedback: z.enum(["kept", "skipped"]).nullable(),
  /** Set when keeping the item added it to a playlist (undo target). */
  journal_id: z.number().nullable(),
  _links: halLinksSchema,
});

export const radioSummarySchema = z.object({
  kept: z.number(),
  skipped: z.number(),
  added: z.number(),
  pending: z.number(),
});

export const radioSessionSchema = z.object({
  id: z.number(),
  seed_kind: z.enum(["playlist", "tracks", "genre"]),
  seed_playlist_id: z.number().nullable(),
  seed_genre: z.string().nullable(),
  label: z.string(),
  discovery_ratio: z.number(),
  items: z.array(radioItemSchema),
  summary: radioSummarySchema,
  _links: halLinksSchema,
});

// ----------------------------------------------- insights (Task 26 survey)

/**
 * The survey payload — one section-shaped reading of the whole library.
 * Every field is exact per api/crate/router/insights.py; sub-blocks go null
 * or empty before enrichment (the page renders honest pending states rather
 * than hiding sections).
 */

export const insightsCoverageSchema = z.object({
  total_tracks: z.number(),
  enriched_tracks: z.number(),
  library_artists: z.number(),
  dated_tracks: z.number(),
  birth_year_set: z.boolean(),
});

export const fingerprintAxisSchema = z.object({
  feature: z.string(),
  percentile: z.number(),
});

export const genreEntropySchema = z.object({
  entropy_bits: z.number(),
  effective_genres: z.number(),
});

export const typologySchema = z.object({
  archetype: z.string(),
  genre_breadth: z.number(),
  acoustic_sprawl: z.number(),
  rarity: z.number(),
});

export const genreShareSchema = z.object({
  genre: z.string(),
  share: z.number(),
});

export const rarestGenreSchema = z.object({
  genre: z.string(),
  enao_rank: z.number(),
  rarity: z.number(),
});

export const tasteIdentitySchema = z.object({
  fingerprint: z.array(fingerprintAxisSchema),
  genre_entropy: genreEntropySchema,
  /** Acoustic sprawl 0..1; null under 2 enriched tracks. */
  gs_score: z.number().nullable(),
  typology: typologySchema,
  genre_shares: z.array(genreShareSchema),
  genre_rarity: z.object({
    mean_rarity: z.number(),
    rarest: z.array(rarestGenreSchema),
  }),
});

export const camelotSegmentSchema = z.object({
  code: z.string(),
  number: z.number(),
  ring: z.string(),
  count: z.number(),
  /** Mean valence tint for the key; null with no enriched tracks in it. */
  mean_valence: z.number().nullable(),
});

export const moodSchema = z.object({
  grid: z.array(z.array(z.number())),
  size: z.number(),
  counts: z.record(z.string(), z.number()),
  shares: z.record(z.string(), z.number()),
  total: z.number(),
});

export const tempoBandSchema = z.object({
  bpm_low: z.number(),
  bpm_high: z.number(),
  count: z.number(),
});

export const ridgelineSchema = z.object({
  feature: z.string(),
  buckets: z.array(z.number()),
});

export const sonicSignaturesSchema = z.object({
  camelot: z.array(camelotSegmentSchema),
  mood: moodSchema,
  tempo: z.array(tempoBandSchema),
  ridgelines: z.array(ridgelineSchema),
});

export const addsOverTimeSchema = z.object({
  month: z.string(),
  count: z.number(),
  /** Mean color of that month's enriched adds; null if none enriched. */
  centroid: centroidSchema.nullable(),
});

export const abandonedPlaylistSchema = z.object({
  playlist_id: z.number(),
  name: z.string(),
  months_dormant: z.number(),
});

export const archaeologySchema = z.object({
  adds_over_time: z.array(addsOverTimeSchema),
  abandoned_playlists: z.array(abandonedPlaylistSchema),
});

export const decadeSchema = z.object({
  decade: z.number(),
  count: z.number(),
});

export const comingOfAgeSchema = z.object({
  band_start_year: z.number(),
  band_end_year: z.number(),
  share: z.number(),
  count: z.number(),
});

export const erasSchema = z.object({
  decades: z.array(decadeSchema),
  center_of_gravity: z.number().nullable(),
  median_year: z.number().nullable(),
  /** Populated only when birth_year is set. */
  coming_of_age: comingOfAgeSchema.nullable(),
  total: z.number(),
});

export const extremeSchema = z.object({
  label: z.string(),
  track_id: z.number(),
  name: z.string(),
  artist: z.string(),
  value: z.number(),
  /** "seconds" for duration extremes, "percentile" for feature extremes. */
  unit: z.string(),
});

export const insightsSchema = z.object({
  coverage: insightsCoverageSchema,
  taste_identity: tasteIdentitySchema,
  sonic_signatures: sonicSignaturesSchema,
  archaeology: archaeologySchema,
  eras: erasSchema,
  extremes: z.array(extremeSchema),
  _links: halLinksSchema,
});

// ----------------------------------------- insight editions (field journal)

export const editionNarrativeSchema = z.object({
  /** baseline | entropy | sprawl | rarity | archetype | dormancy | fingerprint | steady */
  kind: z.string(),
  text: z.string(),
});

export const editionSchema = z.object({
  id: z.number(),
  edition_number: z.number(),
  week_start: z.string(),
  generated_at: z.string(),
  owned_only: z.boolean(),
  headline: z.record(z.string(), z.unknown()),
  narrative: z.array(editionNarrativeSchema),
  _links: halLinksSchema,
});

export const editionSummarySchema = z.object({
  id: z.number(),
  edition_number: z.number(),
  week_start: z.string(),
  generated_at: z.string(),
  owned_only: z.boolean(),
  line_count: z.number(),
  _links: halLinksSchema,
});

export const editionCollectionSchema = z.object({
  items: z.array(editionSummarySchema),
  total: z.number(),
  _links: halLinksSchema,
});

// -------------------------------------------------- insight pins (surface C)

export const insightPinSchema = z.object({
  /** node id, "region", or artist key — resolved per surface. */
  anchor: z.string(),
  metric_ref: z.string(),
  line: z.string(),
  /** Stable identity used to remember a dismissal. */
  dismissible_id: z.string(),
  salience: z.number(),
});

export const insightPinsSchema = z.object({
  surface: z.string(),
  pins: z.array(insightPinSchema),
  _links: halLinksSchema,
});

// ----------------------------------------------------------------- triage

/** The account's current triage source. */
export const triageSettingSchema = z.object({
  source: z.enum(["liked", "playlist"]),
  playlist_id: z.number().nullable(),
  playlist_name: z.string().nullable().optional(),
  _links: halLinksSchema,
});

/** One song in the triage queue — the payload carries no artwork. */
export const queueTrackSchema = z.object({
  track_id: z.number(),
  spotify_id: z.string(),
  name: z.string(),
});

export const queueCollectionSchema = z.object({
  items: z.array(queueTrackSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  source: z.enum(["liked", "playlist"]),
  /** The ≤N filter in effect (liked mode only). */
  max_playlists: z.number(),
  _links: halLinksSchema,
});

/** A named filing signal — never blended into one score. */
export const evidenceKindSchema = z.enum([
  "sonic_fit",
  "artist_overlap",
  "placement_history",
  "vibe_match",
]);

export const evidenceSchema = z.object({
  kind: evidenceKindSchema,
  score: z.number(),
  summary: z.string(),
  /** Structured backing for the signal (agreeing axes, counts, neighbours). */
  detail: z.record(z.string(), z.unknown()).optional(),
});

/** One candidate destination playlist with its four separately-labeled signals. */
export const destinationSuggestionSchema = z.object({
  playlist_id: z.number(),
  name: z.string(),
  rank: z.number(),
  /** True when the track is already here — greyed + badge, still selectable. */
  already_in: z.boolean(),
  evidence: z.array(evidenceSchema),
});

export const triageMembershipSchema = z.object({
  count: z.number(),
  playlist_ids: z.array(z.number()),
  playlist_names: z.array(z.string()),
  /** Per membership: whether that playlist is held out of triage (badge it). */
  excluded: z.array(z.boolean()),
});

/** A cluster-grounded new-playlist proposal (founding members listed). */
export const clusterProposalSchema = z.object({
  suggested_name: z.string(),
  founding_track_ids: z.array(z.number()),
  size: z.number(),
});

/**
 * The new-category panel. `pending` = the background clusterer is running
 * (poll again); `empty` = the queue is below the clustering floor.
 */
export const newCategorySchema = z.object({
  status: z.enum(["ready", "pending", "empty"]),
  proposals: z.array(clusterProposalSchema),
});

export const triageIntelligenceSchema = z.object({
  track_id: z.number(),
  suggestions: z.array(destinationSuggestionSchema),
  memberships: triageMembershipSchema,
  new_category: newCategorySchema,
  _links: halLinksSchema,
});

export const triageApplyResultSchema = z.object({
  journal_id: z.number(),
  status: z.string(),
  _links: halLinksSchema,
});

export const triageCleanupResultSchema = z.object({
  journal_id: z.number(),
  status: z.string(),
  removed: z.number(),
  _links: halLinksSchema,
});

/** One owned live playlist in the destinations-management view. */
export const triageDestinationSchema = z.object({
  id: z.number(),
  name: z.string(),
  image_url: z.string().nullable().optional(),
  track_count: z.number(),
  /** True when held out of triage — not a filing destination. */
  triage_excluded: z.boolean(),
});

export const triageDestinationCollectionSchema = z.object({
  items: z.array(triageDestinationSchema),
  total: z.number(),
  excluded_count: z.number(),
  _links: halLinksSchema,
});

// -------------------------------------------------------------- me (Task 26)

export const meSchema = z.object({
  id: z.number(),
  birth_year: z.number().nullable(),
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
export type MapPoint = z.infer<typeof mapPointSchema>;
export type TrackMapResponse = z.infer<typeof trackMapResponseSchema>;
export type GalaxyNode = z.infer<typeof galaxyNodeSchema>;
export type GalaxyEdge = z.infer<typeof galaxyEdgeSchema>;
export type ArtistGalaxyResponse = z.infer<typeof artistGalaxyResponseSchema>;
export type TerritoryGenre = z.infer<typeof territoryGenreSchema>;
export type FrontierGenre = z.infer<typeof frontierGenreSchema>;
export type FrontierResponse = z.infer<typeof frontierResponseSchema>;
export type PlaylistAnalytics = z.infer<typeof playlistAnalyticsSchema>;
export type LibraryStats = z.infer<typeof libraryStatsSchema>;
export type MutationResult = z.infer<typeof mutationResultSchema>;
export type ManifestTrackRef = z.infer<typeof manifestTrackRefSchema>;
export type ManifestRemoveRef = z.infer<typeof manifestRemoveRefSchema>;
export type ManifestEntry = z.infer<typeof manifestEntrySchema>;
export type Manifest = z.infer<typeof manifestSchema>;
export type OpPreview = z.infer<typeof opPreviewSchema>;
export type ApplyResult = z.infer<typeof applyResultSchema>;
export type JournalEntry = z.infer<typeof journalEntrySchema>;
export type JournalCollection = z.infer<typeof journalCollectionSchema>;
export type FitBreakdown = z.infer<typeof fitBreakdownSchema>;
export type FingerprintPoint = z.infer<typeof fingerprintPointSchema>;
export type Suggestion = z.infer<typeof suggestionSchema>;
export type SuggestionQueue = z.infer<typeof suggestionQueueSchema>;
export type FeedbackResult = z.infer<typeof feedbackResultSchema>;
export type DiscoveryRunResult = z.infer<typeof discoveryRunResultSchema>;
export type DigestSection = z.infer<typeof digestSectionSchema>;
export type DigestItem = z.infer<typeof digestItemSchema>;
export type Digest = z.infer<typeof digestSchema>;
export type DigestSummary = z.infer<typeof digestSummarySchema>;
export type DigestCollection = z.infer<typeof digestCollectionSchema>;
export type RadioItem = z.infer<typeof radioItemSchema>;
export type RadioSummary = z.infer<typeof radioSummarySchema>;
export type RadioSession = z.infer<typeof radioSessionSchema>;
export type InsightsCoverage = z.infer<typeof insightsCoverageSchema>;
export type FingerprintAxis = z.infer<typeof fingerprintAxisSchema>;
export type TasteIdentity = z.infer<typeof tasteIdentitySchema>;
export type Typology = z.infer<typeof typologySchema>;
export type GenreShare = z.infer<typeof genreShareSchema>;
export type RarestGenre = z.infer<typeof rarestGenreSchema>;
export type CamelotSegment = z.infer<typeof camelotSegmentSchema>;
export type Mood = z.infer<typeof moodSchema>;
export type TempoBand = z.infer<typeof tempoBandSchema>;
export type Ridgeline = z.infer<typeof ridgelineSchema>;
export type SonicSignatures = z.infer<typeof sonicSignaturesSchema>;
export type AddsOverTime = z.infer<typeof addsOverTimeSchema>;
export type AbandonedPlaylist = z.infer<typeof abandonedPlaylistSchema>;
export type Archaeology = z.infer<typeof archaeologySchema>;
export type Decade = z.infer<typeof decadeSchema>;
export type ComingOfAge = z.infer<typeof comingOfAgeSchema>;
export type Eras = z.infer<typeof erasSchema>;
export type Extreme = z.infer<typeof extremeSchema>;
export type Insights = z.infer<typeof insightsSchema>;
export type EditionNarrative = z.infer<typeof editionNarrativeSchema>;
export type Edition = z.infer<typeof editionSchema>;
export type EditionSummary = z.infer<typeof editionSummarySchema>;
export type EditionCollection = z.infer<typeof editionCollectionSchema>;
export type InsightPin = z.infer<typeof insightPinSchema>;
export type InsightPins = z.infer<typeof insightPinsSchema>;
export type Me = z.infer<typeof meSchema>;
export type TriageSetting = z.infer<typeof triageSettingSchema>;
export type QueueTrack = z.infer<typeof queueTrackSchema>;
export type QueueCollection = z.infer<typeof queueCollectionSchema>;
export type EvidenceKind = z.infer<typeof evidenceKindSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type DestinationSuggestion = z.infer<typeof destinationSuggestionSchema>;
export type TriageMembership = z.infer<typeof triageMembershipSchema>;
export type ClusterProposal = z.infer<typeof clusterProposalSchema>;
export type NewCategory = z.infer<typeof newCategorySchema>;
export type TriageIntelligence = z.infer<typeof triageIntelligenceSchema>;
export type TriageApplyResult = z.infer<typeof triageApplyResultSchema>;
export type TriageCleanupResult = z.infer<typeof triageCleanupResultSchema>;
export type TriageDestination = z.infer<typeof triageDestinationSchema>;
export type TriageDestinationCollection = z.infer<
  typeof triageDestinationCollectionSchema
>;
