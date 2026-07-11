/**
 * Artist-galaxy pure logic: edge styling and bridge highlighting.
 *
 * Edge kinds follow the rendering spec's redundancy rule — relation kind is
 * carried by LINE STYLE, never hue: co-playlist edges are solid (structural,
 * like the graph's overlap edges), similarity edges are dashed 3-2 (an
 * externally asserted relation, like the subset dash).
 */

export type GalaxyEdgeKind = "co_playlist" | "similarity";

/** Shared-playlist count at which a co-playlist edge reaches full width. */
export const CO_EDGE_SATURATION = 8;

export function galaxyEdgeWidth(kind: GalaxyEdgeKind, weight: number): number {
  if (kind === "similarity") {
    return 1 + 1.5 * Math.min(1, weight);
  }
  return 0.75 + 2.25 * Math.min(1, weight / CO_EDGE_SATURATION);
}

export function galaxyEdgeDash(kind: GalaxyEdgeKind): number[] | null {
  return kind === "similarity" ? [3, 2] : null;
}

/**
 * Legend pin behavior: up to two playlists pinned at once (the bridge pair).
 * Pinning a third rotates the oldest out; clicking a pinned one unpins it.
 */
export function togglePin(pins: number[], playlistId: number): number[] {
  if (pins.includes(playlistId)) {
    return pins.filter((id) => id !== playlistId);
  }
  const next = [...pins, playlistId];
  return next.length > 2 ? next.slice(next.length - 2) : next;
}

/**
 * The highlight set for the current pins: artists appearing in EVERY pinned
 * playlist (intersection semantics — two pins show the bridge between them).
 * Null when nothing is pinned (no highlight veil).
 */
export function bridgingArtists(
  nodes: Array<{ id: string; playlist_ids: number[] }>,
  pins: number[],
): Set<string> | null {
  if (pins.length === 0) return null;
  const matches = nodes.filter((node) =>
    pins.every((pin) => node.playlist_ids.includes(pin)),
  );
  return new Set(matches.map((node) => node.id));
}
