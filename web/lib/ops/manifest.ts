/**
 * Delta-manifest presentation: flattens the API's per-playlist manifest into
 * table rows and derives the switchgear's labels. Pure functions — the
 * manifest table and COMMIT copy are asserted in unit tests.
 */

import type { Manifest } from "@/lib/api/schemas";

export interface ManifestRow {
  key: string;
  playlist: string;
  delta: "add" | "remove";
  title: string;
  artist: string;
  /** 0-based playlist position for removals; adds append. */
  position: number | null;
}

/** Adds before removes within each entry, entries in manifest order. */
export function manifestRows(manifest: Manifest): ManifestRow[] {
  const rows: ManifestRow[] = [];
  for (const entry of manifest.entries) {
    for (const add of entry.adds) {
      rows.push({
        key: `${entry.playlist_name}-add-${add.track_id}-${rows.length}`,
        playlist: entry.playlist_name,
        delta: "add",
        title: add.name,
        artist: add.artist,
        position: null,
      });
    }
    for (const remove of entry.removes) {
      rows.push({
        key: `${entry.playlist_name}-rem-${remove.track_id}-${remove.position}`,
        playlist: entry.playlist_name,
        delta: "remove",
        title: remove.name,
        artist: remove.artist,
        position: remove.position,
      });
    }
  }
  return rows;
}

/** "COMMIT −12 / +87" — removes first, matching the mockup's emphasis. */
export function commitLabel(manifest: Manifest): string {
  const { adds, removes } = manifest.summary;
  const parts: string[] = [];
  if (removes > 0) parts.push(`−${removes}`);
  if (adds > 0) parts.push(`+${adds}`);
  return parts.length > 0 ? `COMMIT ${parts.join(" / ")}` : "COMMIT";
}

/** Removing tracks paints COMMIT in danger red; add-only ops stay amber. */
export function commitIsDestructive(manifest: Manifest): boolean {
  return manifest.summary.removes > 0;
}

/** An empty delta means there is nothing to apply. */
export function manifestIsEmpty(manifest: Manifest): boolean {
  return manifest.summary.adds === 0 && manifest.summary.removes === 0;
}
