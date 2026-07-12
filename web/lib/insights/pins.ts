/**
 * Insight-pin anchor resolution — the annotated-atlas layer (surface C).
 *
 * A pin's `anchor` is surface-specific: a playlist node id, a canvas region,
 * an artist key, or a fingerprint axis. This resolves each anchor to a human
 * label and a target (for a deep-link when the anchor names a real entity),
 * so the render layer stays declarative. Pure logic — unit-tested.
 */

import type { GraphNode, InsightPin } from "@/lib/api/schemas";

export type PinSurface = "graph" | "field" | "galaxy";

export interface ResolvedPin {
  pin: InsightPin;
  /** Human label for the anchor (playlist name, artist, region, axis). */
  anchorLabel: string;
  /** Deep-link target when the anchor names an openable entity. */
  target:
    | { kind: "playlist"; id: number }
    | { kind: "artist"; id: string }
    | { kind: "none" };
}

/**
 * Resolve pins for a surface against the live graph nodes (used to turn a
 * `playlist:{id}` anchor into a name + open target). Order is preserved —
 * the API already ranks by salience.
 */
export function resolvePins(
  pins: InsightPin[],
  nodes: GraphNode[],
): ResolvedPin[] {
  const byId = new Map(nodes.map((n) => [n.id, n.name]));
  return pins.map((pin) => resolveOne(pin, byId));
}

function resolveOne(
  pin: InsightPin,
  playlistNames: Map<number, string>,
): ResolvedPin {
  const anchor = pin.anchor;

  // playlist:{id} — most-dormant/rarest playlist pins on the graph surface.
  const playlistMatch = anchor.match(/^playlist:(\d+)$/);
  if (playlistMatch) {
    const id = Number.parseInt(playlistMatch[1], 10);
    return {
      pin,
      anchorLabel: playlistNames.get(id) ?? `Playlist ${id}`,
      target: { kind: "playlist", id },
    };
  }

  // genre:{name} — rarest-genre pins.
  const genreMatch = anchor.match(/^genre:(.+)$/);
  if (genreMatch) {
    return { pin, anchorLabel: genreMatch[1], target: { kind: "none" } };
  }

  // quadrant:{name} / region:{name} — canvas-region pins (field surface).
  const regionMatch = anchor.match(/^(?:quadrant|region):(.+)$/);
  if (regionMatch) {
    return {
      pin,
      anchorLabel: humanizeToken(regionMatch[1]),
      target: { kind: "none" },
    };
  }

  // Bare fingerprint axis (energy, valence, …) — field surface.
  if (pin.metric_ref === "fingerprint") {
    return {
      pin,
      anchorLabel: humanizeToken(anchor),
      target: { kind: "none" },
    };
  }

  // Otherwise treat the anchor as an artist key (galaxy surface) — the node
  // id in the artist galaxy is the lowercased artist name.
  return {
    pin,
    anchorLabel: humanizeToken(anchor),
    target: { kind: "artist", id: anchor },
  };
}

/** "happy_energetic" → "Happy energetic"; "energy" → "Energy". */
export function humanizeToken(token: string): string {
  const spaced = token.replace(/[_:]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Filter out pins the user has dismissed and cap at the surface's visible
 * count. Dismissed ids are matched against `dismissible_id`.
 */
export function visiblePins(
  resolved: ResolvedPin[],
  dismissed: Set<string>,
  max: number,
): ResolvedPin[] {
  return resolved
    .filter((r) => !dismissed.has(r.pin.dismissible_id))
    .slice(0, max);
}
