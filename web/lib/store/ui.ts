"use client";

import { create } from "zustand";
import type { FlyId, FlyTarget } from "@/lib/canvas/fly-to";

/**
 * Dock-layer state. The map is the room: everything else is a panel docked
 * over it, one right panel at a time, Escape pops one layer top-down
 * (palette → right panel → nothing).
 */
export type RightPanel =
  | { kind: "playlist"; playlistId: number }
  | { kind: "stats" }
  | { kind: "bulk-ops"; sourceId?: number }
  | { kind: "ops-log" }
  | { kind: "track"; trackId: number }
  | { kind: "artist"; artistId: string }
  | { kind: "frontier" }
  | { kind: "inbox" }
  | { kind: "radio" }
  | { kind: "insights" }
  | { kind: "triage" };

/**
 * The canvas renders one of three maps: the playlist graph, the track field,
 * or the artist galaxy — the canvas trinity. New surfaces beyond these dock
 * as panels instead (the frontier explorer is a panel, not a fourth mode).
 */
export type MapMode = "playlists" | "tracks" | "artists";

/**
 * How the field colours its points (G4). `acoustic` = rank-equalized acoustic
 * colour (the default: colour = sound, spread across the gamut); `cluster` =
 * each density cluster gets a distinct base hue, shaded within by acoustics.
 */
export type PaletteMode = "acoustic" | "cluster";

/**
 * Surfaces that carry a field guide: the three canvas modes plus the
 * frontier and insights panels (panels, not map modes — hence the wider
 * union).
 */
export type FieldGuideMode = MapMode | "frontier" | "insights";

/** A track picked in the playlist panel — target of graph context-menu adds. */
export interface SelectedTrack {
  trackId: number;
  name: string;
}

interface UiState {
  rightPanel: RightPanel | null;
  paletteOpen: boolean;
  /** Whether the browsable glossary index overlay is open. */
  glossaryOpen: boolean;
  /**
   * Whether the map and library analytics also cover followed playlists.
   * Off by default: followed playlists outnumber owned ones several times
   * over, and the map is designed around the curated set.
   */
  includeFollowed: boolean;
  /** Which map fills the room: playlist graph (force) or track field (scatter). */
  mapMode: MapMode;
  /** Track-field HDBSCAN hulls on/off. */
  clusterOverlay: boolean;
  /** Field point palette: rank-equalized acoustic colour, or cluster-keyed (G4). */
  paletteMode: PaletteMode;
  /** Node selected on the map (drives the selection ring + playlist panel). */
  selectedPlaylistId: number | null;
  /** G5 — the active search-to-focus fly-to target (mode + id + nonce). */
  flyTarget: FlyTarget | null;
  /** Tracks marked in the playlist panel, for "add selection to…" actions. */
  selectedTracks: SelectedTrack[];
  /**
   * Per-mode field guide expanded/collapsed state. Keyed by FieldGuideMode.
   * A mode absent from this record has never been visited — defaults to
   * expanded on first visit (see fieldGuideFirstVisit).
   */
  fieldGuideExpanded: Partial<Record<FieldGuideMode, boolean>>;
  /**
   * Tracks whether the user has ever toggled the guide for a mode.
   * Until toggled, the guide renders expanded.
   */
  fieldGuideFirstVisit: Partial<Record<FieldGuideMode, boolean>>;
  openPlaylist: (playlistId: number) => void;
  openTrack: (trackId: number) => void;
  openArtist: (artistId: string) => void;
  openFrontier: () => void;
  openInbox: () => void;
  openRadio: () => void;
  openInsights: () => void;
  openTriage: () => void;
  setMapMode: (mode: MapMode) => void;
  setClusterOverlay: (on: boolean) => void;
  setPaletteMode: (mode: PaletteMode) => void;
  /** Switch to the target's map mode and fly the camera to it (⌘K search). */
  flyToNode: (mode: MapMode, id: FlyId) => void;
  openStats: () => void;
  openBulkOps: (sourceId?: number) => void;
  openOpsLog: () => void;
  closeRightPanel: () => void;
  setPaletteOpen: (open: boolean) => void;
  openGlossary: () => void;
  closeGlossary: () => void;
  setIncludeFollowed: (include: boolean) => void;
  toggleTrackSelection: (track: SelectedTrack) => void;
  clearTrackSelection: () => void;
  popLayer: () => void;
  setFieldGuideExpanded: (mode: FieldGuideMode, expanded: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  rightPanel: null,
  paletteOpen: false,
  glossaryOpen: false,
  includeFollowed: false,
  mapMode: "playlists",
  clusterOverlay: false,
  paletteMode: "acoustic",
  selectedPlaylistId: null,
  flyTarget: null,
  selectedTracks: [],
  fieldGuideExpanded: {},
  fieldGuideFirstVisit: {},

  openTrack: (trackId) =>
    set({ rightPanel: { kind: "track", trackId }, paletteOpen: false }),

  openArtist: (artistId) =>
    set({ rightPanel: { kind: "artist", artistId }, paletteOpen: false }),

  openFrontier: () =>
    set({ rightPanel: { kind: "frontier" }, paletteOpen: false }),

  openInbox: () => set({ rightPanel: { kind: "inbox" }, paletteOpen: false }),

  openRadio: () => set({ rightPanel: { kind: "radio" }, paletteOpen: false }),

  openInsights: () =>
    set({ rightPanel: { kind: "insights" }, paletteOpen: false }),

  openTriage: () => set({ rightPanel: { kind: "triage" }, paletteOpen: false }),

  setMapMode: (mode) => set({ mapMode: mode }),

  setClusterOverlay: (on) => set({ clusterOverlay: on }),

  setPaletteMode: (mode) => set({ paletteMode: mode }),

  flyToNode: (mode, id) =>
    set(() => ({
      mapMode: mode,
      paletteOpen: false,
      // Clock nonce so this is comparable with the graph's transport/deck fly.
      flyTarget: { mode, id, nonce: Date.now() },
    })),

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

  openGlossary: () => set({ glossaryOpen: true, paletteOpen: false }),
  closeGlossary: () => set({ glossaryOpen: false }),

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
    const { paletteOpen, glossaryOpen, rightPanel } = get();
    if (glossaryOpen) {
      set({ glossaryOpen: false });
    } else if (paletteOpen) {
      set({ paletteOpen: false });
    } else if (rightPanel) {
      set({ rightPanel: null, selectedPlaylistId: null, selectedTracks: [] });
    }
  },

  setFieldGuideExpanded: (mode, expanded) => {
    const { fieldGuideExpanded, fieldGuideFirstVisit } = get();
    set({
      fieldGuideExpanded: { ...fieldGuideExpanded, [mode]: expanded },
      fieldGuideFirstVisit: { ...fieldGuideFirstVisit, [mode]: true },
    });
  },
}));
