"use client";

import { useDismissedPinSet, usePinsStore } from "@/lib/store/pins";

/**
 * PINS SHOWN/HIDDEN — the chrome switch for the annotated-atlas layer,
 * mirroring the FOLLOWED toggle. Toggling to SHOWN also restores any
 * dismissed pins (the "bring them back" affordance): if pins are hidden OR
 * some have been dismissed, the switch reads HIDDEN and one click brings the
 * full set back.
 */
export function PinsSwitch() {
  const hidden = usePinsStore((s) => s.hidden);
  const dismissed = useDismissedPinSet();
  const setHidden = usePinsStore((s) => s.setHidden);
  const restoreAll = usePinsStore((s) => s.restoreAll);

  // "Effectively hidden" = globally hidden, or all live pins dismissed.
  const suppressed = hidden || dismissed.size > 0;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={!suppressed}
      onClick={() => {
        if (suppressed) {
          restoreAll();
        } else {
          setHidden(true);
        }
      }}
      title="Insight pins annotate the map — dismiss individually, or hide/show all here"
      className={`micro-caps pointer-events-auto cursor-pointer ${
        suppressed
          ? "text-text-muted hover:text-text-secondary"
          : "text-text-primary"
      }`}
    >
      PINS {suppressed ? "HIDDEN" : "SHOWN"}
    </button>
  );
}
