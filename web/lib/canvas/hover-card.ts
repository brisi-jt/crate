/**
 * Rich hover-card view models.
 *
 * One shell component renders every hover card; this module maps a node
 * (track / artist / playlist / genre) into the card's display data. Pure — no
 * DOM, no image decode — so the fields, fingerprint readout, and viewport
 * clamping are unit-tested and the component is a thin renderer. Imagery fields
 * come from the imagery backfill (album_image_url, artist image_url, playlist
 * image_url) exposed in the map/galaxy/graph payloads.
 */

import type { GalaxyNode, MapPoint } from "@/lib/api/schemas";
import type { AcousticCentroid } from "@/lib/color/acoustic";

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}

export interface FingerprintBar {
  label: string;
  value: number;
}

/** Energy / valence / acousticness as compact 0..1 readouts, in that order. */
export function fingerprintBars(f: AcousticCentroid): FingerprintBar[] {
  return [
    { label: "NRG", value: clamp01(f.energy) },
    { label: "VAL", value: clamp01(f.valence) },
    { label: "ACO", value: clamp01(f.acousticness) },
  ];
}

export interface TrackCardModel {
  kind: "track";
  title: string;
  subtitle: string;
  imageUrl: string | null;
  clusterId: number | null;
  playlistCount: number;
  fingerprint: FingerprintBar[] | null;
}

export function trackCardModel(point: MapPoint): TrackCardModel {
  return {
    kind: "track",
    title: point.name,
    subtitle: point.artist,
    imageUrl: point.album_image_url ?? null,
    clusterId: point.cluster >= 0 ? point.cluster : null,
    playlistCount: point.playlist_ids?.length ?? 0,
    fingerprint: point.features ? fingerprintBars(point.features) : null,
  };
}

export interface ArtistCardModel {
  kind: "artist";
  title: string;
  imageUrl: string | null;
  trackCount: number;
  playlistCount: number;
  genres: string[];
  similar: Array<{ name: string; inLibrary: boolean }>;
}

const MAX_GENRES = 3;
const MAX_SIMILAR = 3;

export function artistCardModel(node: GalaxyNode): ArtistCardModel {
  return {
    kind: "artist",
    title: node.name,
    imageUrl: node.image_url ?? null,
    trackCount: node.track_count,
    playlistCount: node.playlist_count,
    genres: node.genres.slice(0, MAX_GENRES),
    similar: node.similar.slice(0, MAX_SIMILAR).map((s) => ({
      name: s.name,
      inLibrary: s.in_library,
    })),
  };
}

export interface CardBox {
  width: number;
  height: number;
}

export interface CardBounds {
  width: number;
  height: number;
  /** Docked-panel width in px — trims the usable right edge. */
  rightInset?: number;
}

export interface CardPosition {
  left: number;
  top: number;
}

const CURSOR_OFFSET = 18;
const EDGE_MARGIN = 12;

/**
 * Position the card down-right of the cursor, flipped and clamped so it stays
 * fully inside the container (respecting a docked right panel).
 */
export function clampCardPosition(
  cursorX: number,
  cursorY: number,
  card: CardBox,
  bounds: CardBounds,
): CardPosition {
  const usableRight = bounds.width - (bounds.rightInset ?? 0) - EDGE_MARGIN;
  const usableBottom = bounds.height - EDGE_MARGIN;

  let left = cursorX + CURSOR_OFFSET;
  if (left + card.width > usableRight) {
    // Flip to the left of the cursor; clamp to the left margin if still tight.
    left = Math.max(EDGE_MARGIN, cursorX - CURSOR_OFFSET - card.width);
    if (left + card.width > usableRight) {
      left = Math.max(EDGE_MARGIN, usableRight - card.width);
    }
  }

  let top = cursorY + CURSOR_OFFSET;
  if (top + card.height > usableBottom) {
    top = Math.max(EDGE_MARGIN, cursorY - CURSOR_OFFSET - card.height);
    if (top + card.height > usableBottom) {
      top = Math.max(EDGE_MARGIN, usableBottom - card.height);
    }
  }

  return { left, top };
}
