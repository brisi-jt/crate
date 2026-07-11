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
};
