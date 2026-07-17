"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Insight-pin client state.
 *
 *  - `dismissed` — dismissed `dismissible_id`s. A dismissed pin stays gone
 *    until the user brings pins back. Persisted (localStorage): closing a pin
 *    is sticky, not per-session.
 *  - `hidden` — the global PINS SHOWN/HIDDEN switch, mirroring the FOLLOWED
 *    chrome toggle.
 *  - `seed` — the per-session rotation seed for the client-side sampler. The
 *    same seed reproduces the same sample (no flicker on re-render); the
 *    "shuffle pins" action rolls a new one so a refresh brings fresh pins.
 *  - `shownHistory` — how many recent sessions each `dismissible_id` has been
 *    shown in, so the sampler can down-weight the ones the user keeps seeing.
 *    Persisted so rotation survives reloads.
 */
interface PinsState {
  /** Dismissed `dismissible_id`s. */
  dismissed: string[];
  /** Global pin visibility switch. */
  hidden: boolean;
  /** Session rotation seed for the sampler. */
  seed: number;
  /** `dismissible_id` → recent-session appearance count (anti-repeat weight). */
  shownHistory: Record<string, number>;
  dismiss: (id: string) => void;
  /** Un-dismiss everything and show pins again (the "bring them back" action). */
  restoreAll: () => void;
  setHidden: (hidden: boolean) => void;
  /** Roll a fresh rotation seed — the "shuffle pins" action. */
  reshuffle: () => void;
  /** Record that these ids were shown this session (bumps their history). */
  recordShown: (ids: string[]) => void;
}

/** A fresh 32-bit-ish seed. */
function rollSeed(): number {
  return Math.floor(Math.random() * 0xffffffff);
}

export const usePinsStore = create<PinsState>()(
  persist(
    (set, get) => ({
      dismissed: [],
      hidden: false,
      seed: rollSeed(),
      shownHistory: {},
      dismiss: (id) => {
        if (get().dismissed.includes(id)) return;
        set({ dismissed: [...get().dismissed, id] });
      },
      restoreAll: () => set({ dismissed: [], hidden: false }),
      setHidden: (hidden) => set({ hidden }),
      reshuffle: () => set({ seed: rollSeed() }),
      recordShown: (ids) => {
        if (ids.length === 0) return;
        const next = { ...get().shownHistory };
        for (const id of ids) {
          next[id] = (next[id] ?? 0) + 1;
        }
        set({ shownHistory: next });
      },
    }),
    {
      name: "crate-insight-pins",
      // Seed is per-session — never persist it, so every fresh session rotates.
      partialize: (state) => ({
        dismissed: state.dismissed,
        hidden: state.hidden,
        shownHistory: state.shownHistory,
      }),
    },
  ),
);

/** Selector: a Set of dismissed ids for cheap membership checks. */
export function useDismissedPinSet(): Set<string> {
  const dismissed = usePinsStore((s) => s.dismissed);
  return new Set(dismissed);
}
