"use client";

import { create } from "zustand";
import {
  type DeckEvent,
  type DeckState,
  initialDeckState,
  reduce,
} from "@/lib/deck/machine";
import { useUiStore } from "@/lib/store/ui";

/**
 * Listening-deck session state: which playlist is being auditioned plus the
 * pure review machine (queue / position / play intent). The deck component
 * feeds it queue reloads and keyboard events; the transport strip's
 * prev/next buttons drive the same machine while the deck is open.
 */
interface DeckStore extends DeckState {
  /** Target playlist under audition; null = deck closed. */
  playlistId: number | null;
  open: (playlistId: number) => void;
  close: () => void;
  dispatch: (event: DeckEvent) => void;
}

export const useDeckStore = create<DeckStore>((set, get) => ({
  ...initialDeckState,
  playlistId: null,

  open: (playlistId) => set({ ...initialDeckState, playlistId }),

  close: () => set({ ...initialDeckState, playlistId: null }),

  dispatch: (event) => {
    const { queue, index, playing } = get();
    set(reduce({ queue, index, playing }, event));
  },
}));

/**
 * Open the deck over the dimmed map: the right panel retracts (the deck is
 * the focus), the target playlist stays selected so its ring and label hold.
 */
export function openListeningDeck(playlistId: number) {
  useDeckStore.getState().open(playlistId);
  useUiStore.setState({
    rightPanel: null,
    paletteOpen: false,
    selectedPlaylistId: playlistId,
  });
}
