"use client";

import { create } from "zustand";

/**
 * Dock-layer state. The map is the room: everything else is a panel docked
 * over it, one right panel at a time, Escape pops one layer top-down
 * (palette → right panel → nothing).
 */
export type RightPanel =
  | { kind: "playlist"; playlistId: number }
  | { kind: "stats" }
  | { kind: "bulk-ops"; sourceId?: number }
  | { kind: "ops-log" };

/** A track picked in the playlist panel — target of graph context-menu adds. */
export interface SelectedTrack {
  trackId: number;
  name: string;
}

interface UiState {
  rightPanel: RightPanel | null;
  paletteOpen: boolean;
  /**
   * Whether the map and library analytics also cover followed playlists.
   * Off by default: followed playlists outnumber owned ones several times
   * over, and the map is designed around the curated set.
   */
  includeFollowed: boolean;
  /** Node selected on the map (drives the selection ring + playlist panel). */
  selectedPlaylistId: number | null;
  /** Tracks marked in the playlist panel, for "add selection to…" actions. */
  selectedTracks: SelectedTrack[];
  openPlaylist: (playlistId: number) => void;
  openStats: () => void;
  openBulkOps: (sourceId?: number) => void;
  openOpsLog: () => void;
  closeRightPanel: () => void;
  setPaletteOpen: (open: boolean) => void;
  setIncludeFollowed: (include: boolean) => void;
  toggleTrackSelection: (track: SelectedTrack) => void;
  clearTrackSelection: () => void;
  popLayer: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  rightPanel: null,
  paletteOpen: false,
  includeFollowed: false,
  selectedPlaylistId: null,
  selectedTracks: [],

  openPlaylist: (playlistId) =>
    set({
      rightPanel: { kind: "playlist", playlistId },
      selectedPlaylistId: playlistId,
      selectedTracks: [],
      paletteOpen: false,
    }),

  openStats: () => set({ rightPanel: { kind: "stats" }, paletteOpen: false }),

  openBulkOps: (sourceId) =>
    set({ rightPanel: { kind: "bulk-ops", sourceId }, paletteOpen: false }),

  openOpsLog: () =>
    set({ rightPanel: { kind: "ops-log" }, paletteOpen: false }),

  closeRightPanel: () =>
    set({ rightPanel: null, selectedPlaylistId: null, selectedTracks: [] }),

  setPaletteOpen: (open) => set({ paletteOpen: open }),

  setIncludeFollowed: (include) => set({ includeFollowed: include }),

  toggleTrackSelection: (track) => {
    const current = get().selectedTracks;
    const exists = current.some((t) => t.trackId === track.trackId);
    set({
      selectedTracks: exists
        ? current.filter((t) => t.trackId !== track.trackId)
        : [...current, track],
    });
  },

  clearTrackSelection: () => set({ selectedTracks: [] }),

  popLayer: () => {
    const { paletteOpen, rightPanel } = get();
    if (paletteOpen) {
      set({ paletteOpen: false });
    } else if (rightPanel) {
      set({ rightPanel: null, selectedPlaylistId: null, selectedTracks: [] });
    }
  },
}));
