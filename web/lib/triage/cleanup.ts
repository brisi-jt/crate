/**
 * The post-apply removal popup's selection state. Per spec every song starts
 * UNCHECKED — removal from the source is opt-in — with select all / none.
 * Pure, so the checkbox logic and the cleanup-body assembly are testable.
 */

export interface CleanupSong {
  trackId: number;
  name: string;
}

export interface CleanupState {
  songs: CleanupSong[];
  checked: Record<number, boolean>;
}

export type CleanupEvent =
  | { type: "TOGGLE"; trackId: number }
  | { type: "SELECT_ALL" }
  | { type: "SELECT_NONE" };

export function initCleanup(songs: CleanupSong[]): CleanupState {
  const checked: Record<number, boolean> = {};
  for (const song of songs) checked[song.trackId] = false; // default unchecked
  return { songs, checked };
}

export function reduceCleanup(
  state: CleanupState,
  event: CleanupEvent,
): CleanupState {
  switch (event.type) {
    case "TOGGLE":
      return {
        ...state,
        checked: {
          ...state.checked,
          [event.trackId]: !state.checked[event.trackId],
        },
      };
    case "SELECT_ALL": {
      const checked: Record<number, boolean> = {};
      for (const song of state.songs) checked[song.trackId] = true;
      return { ...state, checked };
    }
    case "SELECT_NONE":
      return initCleanup(state.songs);
  }
}

export function cleanupSelectedCount(state: CleanupState): number {
  return state.songs.filter((s) => state.checked[s.trackId]).length;
}

export type CleanupSource =
  | { source: "liked" }
  | { source: "playlist"; playlistId: number };

export interface CleanupBody {
  source: "liked" | "playlist";
  playlist_id?: number;
  track_ids: number[];
}

/** Null when nothing is checked — the caller skips the no-op cleanup call. */
export function cleanupBody(
  state: CleanupState,
  source: CleanupSource,
): CleanupBody | null {
  const trackIds = state.songs
    .filter((s) => state.checked[s.trackId])
    .map((s) => s.trackId);
  if (trackIds.length === 0) return null;

  if (source.source === "playlist") {
    return {
      source: "playlist",
      playlist_id: source.playlistId,
      track_ids: trackIds,
    };
  }
  return { source: "liked", track_ids: trackIds };
}
