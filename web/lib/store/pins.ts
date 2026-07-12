"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Insight-pin dismissal state. Pins are per-surface annotations from
 * GET /v1/insights/pins; a dismissed pin stays gone until the user brings
 * pins back. Dismissals persist across reloads (localStorage) — closing a
 * pin should be sticky, not a per-session thing. `hidden` is the global
 * PINS SHOWN/HIDDEN switch, mirroring the FOLLOWED chrome toggle.
 */
interface PinsState {
  /** Dismissed `dismissible_id`s. */
  dismissed: string[];
  /** Global pin visibility switch. */
  hidden: boolean;
  dismiss: (id: string) => void;
  /** Un-dismiss everything and show pins again (the "bring them back" action). */
  restoreAll: () => void;
  setHidden: (hidden: boolean) => void;
}

export const usePinsStore = create<PinsState>()(
  persist(
    (set, get) => ({
      dismissed: [],
      hidden: false,
      dismiss: (id) => {
        if (get().dismissed.includes(id)) return;
        set({ dismissed: [...get().dismissed, id] });
      },
      restoreAll: () => set({ dismissed: [], hidden: false }),
      setHidden: (hidden) => set({ hidden }),
    }),
    { name: "crate-insight-pins" },
  ),
);

/** Selector: a Set of dismissed ids for cheap membership checks. */
export function useDismissedPinSet(): Set<string> {
  const dismissed = usePinsStore((s) => s.dismissed);
  return new Set(dismissed);
}
