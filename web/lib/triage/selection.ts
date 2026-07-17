/**
 * Destination selection state for one triage song: a set of existing
 * playlists to file into (already-in ones included — the panel greys them but
 * they stay selectable), an optional new playlist to create+seed, and the
 * liked-mode unsave flag. Pure, so the multi-select → single-apply assembly
 * is testable without React.
 */

export interface NewPlaylistDraft {
  name: string;
  /** Cluster members to seed with; the filed track is always added on apply. */
  seedTrackIds: number[];
}

export interface SelectionState {
  destinationIds: number[];
  newPlaylist: NewPlaylistDraft | null;
  unsave: boolean;
}

export type SelectionEvent =
  | { type: "TOGGLE_DEST"; playlistId: number }
  | { type: "SET_NEW_PLAYLIST"; newPlaylist: NewPlaylistDraft | null }
  | { type: "SET_UNSAVE"; unsave: boolean }
  | { type: "RESET" };

export function emptySelection(): SelectionState {
  return { destinationIds: [], newPlaylist: null, unsave: false };
}

export function reduceSelection(
  state: SelectionState,
  event: SelectionEvent,
): SelectionState {
  switch (event.type) {
    case "TOGGLE_DEST": {
      const has = state.destinationIds.includes(event.playlistId);
      return {
        ...state,
        destinationIds: has
          ? state.destinationIds.filter((id) => id !== event.playlistId)
          : [...state.destinationIds, event.playlistId],
      };
    }
    case "SET_NEW_PLAYLIST":
      return { ...state, newPlaylist: event.newPlaylist };
    case "SET_UNSAVE":
      return { ...state, unsave: event.unsave };
    case "RESET":
      return emptySelection();
  }
}

function hasValidNewPlaylist(state: SelectionState): boolean {
  return state.newPlaylist !== null && state.newPlaylist.name.trim().length > 0;
}

/** Apply is enabled once there is at least one real destination. */
export function canApply(state: SelectionState): boolean {
  return state.destinationIds.length > 0 || hasValidNewPlaylist(state);
}

export interface ApplyBody {
  track_id: number;
  destination_playlist_ids?: number[];
  new_playlist?: { name: string; seed_track_ids: number[] };
  unsave?: boolean;
}

export function applyBody(state: SelectionState, trackId: number): ApplyBody {
  const body: ApplyBody = { track_id: trackId };

  if (state.destinationIds.length > 0) {
    body.destination_playlist_ids = [...state.destinationIds];
  }

  if (hasValidNewPlaylist(state) && state.newPlaylist) {
    // The filed track is always seeded, exactly once, alongside the cluster.
    const seed = state.newPlaylist.seedTrackIds.filter((id) => id !== trackId);
    body.new_playlist = {
      name: state.newPlaylist.name.trim(),
      seed_track_ids: [...seed, trackId],
    };
  }

  if (state.unsave) body.unsave = true;

  return body;
}
