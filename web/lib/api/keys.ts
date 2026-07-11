/** Centralized TanStack Query keys — one vocabulary for cache invalidation. */
export const queryKeys = {
  graph: ["graph"] as const,
  playlists: ["playlists"] as const,
  playlistTracks: (playlistId: number, offset: number) =>
    ["playlists", playlistId, "tracks", { offset }] as const,
  playlistAnalytics: (playlistId: number) =>
    ["playlists", playlistId, "analytics"] as const,
  suggestions: (playlistId: number) =>
    ["playlists", playlistId, "suggestions"] as const,
  syncStatus: ["sync", "status"] as const,
  libraryStats: ["library", "stats"] as const,
  journal: ["journal"] as const,
};
