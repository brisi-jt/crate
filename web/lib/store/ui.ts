"use client";

import { create } from "zustand";

/**
 * Dock-layer state. The map is the room: everything else is a panel docked
 * over it, one right panel at a time, Escape pops one layer top-down
 * (palette → right panel → nothing).
 */
export type RightPanel =
  | { kind: "playlist"; playlistId: number }
  | { kind: "stats" };

interface UiState {
  rightPanel: RightPanel | null;
  paletteOpen: boolean;
  /** Node selected on the map (drives the selection ring + playlist panel). */
  selectedPlaylistId: number | null;
  openPlaylist: (playlistId: number) => void;
  openStats: () => void;
  closeRightPanel: () => void;
  setPaletteOpen: (open: boolean) => void;
  popLayer: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  rightPanel: null,
  paletteOpen: false,
  selectedPlaylistId: null,

  openPlaylist: (playlistId) =>
    set({
      rightPanel: { kind: "playlist", playlistId },
      selectedPlaylistId: playlistId,
      paletteOpen: false,
    }),

  openStats: () => set({ rightPanel: { kind: "stats" }, paletteOpen: false }),

  closeRightPanel: () => set({ rightPanel: null, selectedPlaylistId: null }),

  setPaletteOpen: (open) => set({ paletteOpen: open }),

  popLayer: () => {
    const { paletteOpen, rightPanel } = get();
    if (paletteOpen) {
      set({ paletteOpen: false });
    } else if (rightPanel) {
      set({ rightPanel: null, selectedPlaylistId: null });
    }
  },
}));
