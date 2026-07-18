import type { QueueTrack } from "@/lib/api/schemas";

/**
 * The track catalog: a name/identity map accumulated across every loaded page.
 *
 * The queue is paged, and the machine prefetches the next page as it nears the
 * loaded tail. A per-page map (only the currently-fetched page) drops every
 * earlier track — including the CURRENT one — the moment a later page arrives,
 * so the card falls back to "Track NNNNN". This catalog persists entries across
 * page fetches and resets only when the source/filter key changes, mirroring
 * the queue machine's LOADED/APPENDED reset discipline.
 */

export interface TrackCatalog {
  /** The source/filter key these entries belong to (e.g. "liked:0"). */
  key: string;
  /** track_id → its full queue payload. */
  byId: Map<number, QueueTrack>;
}

/** A page of the queue arrived for a given source/filter key. */
export type CatalogEvent = {
  type: "PAGE";
  key: string;
  items: QueueTrack[];
};

export function emptyCatalog(key: string): TrackCatalog {
  return { key, byId: new Map() };
}

export function reduceCatalog(
  state: TrackCatalog,
  event: CatalogEvent,
): TrackCatalog {
  // A key change means a source/filter switch: drop the old catalog wholesale.
  const byId = event.key === state.key ? new Map(state.byId) : new Map();
  for (const item of event.items) byId.set(item.track_id, item);
  return { key: event.key, byId };
}

export function lookupTrack(
  state: TrackCatalog,
  trackId: number,
): QueueTrack | null {
  return state.byId.get(trackId) ?? null;
}
