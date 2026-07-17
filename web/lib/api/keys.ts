/** Centralized TanStack Query keys — one vocabulary for cache invalidation. */
export const queryKeys = {
  graph: ["graph"] as const,
  /** Scope-keyed graph fetch; invalidate with the bare `graph` prefix. */
  graphScoped: (ownedOnly: boolean) => ["graph", { ownedOnly }] as const,
  playlists: ["playlists"] as const,
  playlistTracks: (playlistId: number, offset: number) =>
    ["playlists", playlistId, "tracks", { offset }] as const,
  /** Full track-id roster for one playlist (track-field membership join). */
  playlistTrackIds: (playlistId: number) =>
    ["playlists", playlistId, "track-ids"] as const,
  trackMap: ["track-map"] as const,
  /** Scope-keyed track map; invalidate with the bare `trackMap` prefix. */
  trackMapScoped: (ownedOnly: boolean) => ["track-map", { ownedOnly }] as const,
  galaxy: ["galaxy"] as const,
  /** Scope-keyed artist galaxy; invalidate with the bare `galaxy` prefix. */
  galaxyScoped: (ownedOnly: boolean) => ["galaxy", { ownedOnly }] as const,
  frontier: ["frontier"] as const,
  /** Scope-keyed genre frontier; invalidate with the bare `frontier` prefix. */
  frontierScoped: (ownedOnly: boolean) => ["frontier", { ownedOnly }] as const,
  playlistAnalytics: (playlistId: number) =>
    ["playlists", playlistId, "analytics"] as const,
  suggestions: (playlistId: number) =>
    ["playlists", playlistId, "suggestions"] as const,
  syncStatus: ["sync", "status"] as const,
  libraryStats: ["library", "stats"] as const,
  /** Scope-keyed stats fetch; invalidate with the bare `libraryStats` prefix. */
  libraryStatsScoped: (ownedOnly: boolean) =>
    ["library", "stats", { ownedOnly }] as const,
  journal: ["journal"] as const,
  digests: ["digests"] as const,
  /** One digest with its items; invalidate with the bare `digests` prefix. */
  digest: (digestId: number) => ["digests", digestId] as const,
  radio: (radioId: number) => ["radio", radioId] as const,
  insights: ["insights"] as const,
  /** Scope-keyed survey; invalidate with the bare `insights` prefix. */
  insightsScoped: (ownedOnly: boolean) => ["insights", { ownedOnly }] as const,
  editions: ["editions"] as const,
  /** Scope-keyed edition list; invalidate with the bare `editions` prefix. */
  editionsScoped: (ownedOnly: boolean) => ["editions", { ownedOnly }] as const,
  /** One frozen edition by id. */
  edition: (editionId: number) => ["editions", editionId] as const,
  /** Per-surface insight pins; invalidate with the bare `pins` prefix. */
  insightPins: (surface: string, ownedOnly: boolean) =>
    ["insight-pins", surface, { ownedOnly }] as const,
  me: ["me"] as const,
  /** The account's triage source setting. */
  triageSetting: ["triage", "setting"] as const,
  /** The triage queue for a source + ≤N filter; invalidate with the `triage` prefix. */
  triageQueue: (source: string, maxPlaylists: number) =>
    ["triage", "queue", source, { maxPlaylists }] as const,
  /** Per-track filing intelligence; invalidate one track or the `triage` prefix. */
  triageIntelligence: (trackId: number, maxPlaylists: number) =>
    ["triage", "intelligence", trackId, { maxPlaylists }] as const,
  /**
   * Liked Songs roster. No `saved` key existed before triage — filing that
   * unsaves a track must invalidate it, so it lives here as its own vocabulary.
   */
  saved: ["saved"] as const,
};
