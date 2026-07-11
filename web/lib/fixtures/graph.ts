import type { GraphResponse } from "@/lib/api/schemas";

/**
 * Demo graph payload served when NEXT_PUBLIC_CRATE_GRAPH_FIXTURE=1, standing
 * in for GET /v1/graph/playlists until the analytics engine ships. It goes
 * through the same zod parse as a live response, so it doubles as the
 * contract's reference document.
 *
 * The 14 playlists are the design-mockup archetypes: centroids are chosen so
 * the acoustic color mapping reproduces the exact swatches in the tokens doc
 * §2 (verified in lib/fixtures/graph.test.ts). "New Finds" has no centroid —
 * it demonstrates the enrichment-incomplete grey state.
 */
export const graphFixture: GraphResponse = {
  nodes: [
    {
      id: 1,
      name: "Folk",
      track_count: 48,
      centroid: { acousticness: 0.95, energy: 0.15, valence: 0.45 },
    },
    {
      id: 2,
      name: "Chill Acoustic",
      track_count: 62,
      centroid: { acousticness: 0.85, energy: 0.25, valence: 0.65 },
    },
    {
      id: 3,
      name: "Singer-Songwriter",
      track_count: 66,
      centroid: { acousticness: 0.88, energy: 0.3, valence: 0.556 },
    },
    {
      id: 4,
      name: "Late Night Jazz",
      track_count: 55,
      centroid: { acousticness: 0.9, energy: 0.2, valence: 0.296 },
    },
    {
      id: 5,
      name: "Sunday Morning",
      track_count: 41,
      centroid: { acousticness: 0.6, energy: 0.35, valence: 0.9 },
    },
    {
      id: 6,
      name: "Indie Rock",
      track_count: 120,
      centroid: { acousticness: 0.35, energy: 0.6, valence: 0.556 },
    },
    {
      id: 7,
      name: "Ambient",
      track_count: 73,
      centroid: { acousticness: 0.3, energy: 0.1, valence: 0.259 },
    },
    {
      id: 8,
      name: "Hip-Hop",
      track_count: 96,
      centroid: { acousticness: 0.2, energy: 0.75, valence: 0.5 },
    },
    {
      id: 9,
      name: "Pop",
      track_count: 58,
      centroid: { acousticness: 0.15, energy: 0.9, valence: 0.852 },
    },
    {
      id: 10,
      name: "Gym",
      track_count: 85,
      centroid: { acousticness: 0.05, energy: 0.97, valence: 0.7 },
    },
    {
      id: 11,
      name: "Gym Warmup",
      track_count: 18,
      centroid: { acousticness: 0.01, energy: 0.77, valence: 0.667 },
    },
    {
      id: 12,
      name: "Techno",
      track_count: 44,
      centroid: { acousticness: 0.03, energy: 0.8, valence: 0.352 },
    },
    {
      id: 13,
      name: "Drill",
      track_count: 34,
      centroid: { acousticness: 0.08, energy: 0.85, valence: 0.15 },
    },
    { id: 14, name: "New Finds", track_count: 13, centroid: null },
  ],
  edges: [
    { source: 1, target: 2, shared: 22, subset: false },
    { source: 1, target: 3, shared: 26, subset: false },
    { source: 2, target: 3, shared: 13, subset: false },
    { source: 2, target: 5, shared: 19, subset: false },
    { source: 3, target: 4, shared: 8, subset: false },
    { source: 5, target: 6, shared: 10, subset: false },
    { source: 6, target: 8, shared: 15, subset: false },
    { source: 6, target: 9, shared: 13, subset: false },
    { source: 8, target: 13, shared: 19, subset: false },
    { source: 8, target: 12, shared: 8, subset: false },
    { source: 10, target: 9, shared: 22, subset: false },
    { source: 10, target: 12, shared: 17, subset: false },
    { source: 12, target: 13, shared: 12, subset: false },
    { source: 7, target: 4, shared: 4, subset: false },
    { source: 7, target: 12, shared: 6, subset: false },
    // Gym Warmup ⊂ Gym: all 18 tracks contained — dashed edge + satellite ring.
    { source: 11, target: 10, shared: 18, subset: true },
  ],
  coverage: { enriched_tracks: 627, total_tracks: 640 },
};
