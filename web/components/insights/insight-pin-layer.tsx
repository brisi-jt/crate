"use client";

import { AnimatePresence, motion } from "motion/react";
import { useMemo } from "react";
import { useInsightPins } from "@/hooks/api/use-insights";
import type { GraphNode } from "@/lib/api/schemas";
import {
  type ResolvedPin,
  resolvePins,
  visiblePins,
} from "@/lib/insights/pins";
import { useDismissedPinSet, usePinsStore } from "@/lib/store/pins";
import type { MapMode } from "@/lib/store/ui";
import { useUiStore } from "@/lib/store/ui";

/** Canvas map mode → API pin surface name. */
const SURFACE_FOR_MODE: Record<MapMode, "graph" | "field" | "galaxy"> = {
  playlists: "graph",
  tracks: "field",
  artists: "galaxy",
};

const MAX_VISIBLE = 3;

/**
 * The annotated-atlas layer (surface C): unobtrusive field-manual annotations
 * docked onto the active canvas, one per insight pin. Each is dismissible;
 * dismissals persist. The layer respects the PINS HIDDEN switch and never
 * blocks canvas interaction (pointer-events only on the cards themselves).
 * Pins sit above the field guide, clear of the transport strip.
 */
export function InsightPinLayer({
  mode,
  nodes,
  rightInset,
}: {
  mode: MapMode;
  nodes: GraphNode[];
  rightInset: number;
}) {
  const surface = SURFACE_FOR_MODE[mode];
  const pins = useInsightPins(surface);
  const dismissed = useDismissedPinSet();
  const hidden = usePinsStore((s) => s.hidden);
  const dismiss = usePinsStore((s) => s.dismiss);

  const openPlaylist = useUiStore((s) => s.openPlaylist);
  const openArtist = useUiStore((s) => s.openArtist);
  const setMapMode = useUiStore((s) => s.setMapMode);

  const shown = useMemo(() => {
    const resolved = resolvePins(pins.data?.pins ?? [], nodes);
    return visiblePins(resolved, dismissed, MAX_VISIBLE);
  }, [pins.data, nodes, dismissed]);

  if (hidden || shown.length === 0) return null;

  function openTarget(pin: ResolvedPin) {
    if (pin.target.kind === "playlist") {
      setMapMode("playlists");
      openPlaylist(pin.target.id);
    } else if (pin.target.kind === "artist") {
      setMapMode("artists");
      openArtist(pin.target.id);
    }
  }

  return (
    <div
      className="pointer-events-none absolute bottom-[72px] z-10 flex flex-col items-end gap-xs"
      style={{ right: rightInset + 24 }}
    >
      <AnimatePresence initial={false}>
        {shown.map((r) => (
          <motion.div
            key={r.pin.dismissible_id}
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 8 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="pointer-events-auto w-[260px] rounded-sm border border-border-subtle bg-surface-1/95 p-sm shadow-sm backdrop-blur-sm"
          >
            <div className="mb-2xs flex items-baseline gap-sm">
              <span className="micro-caps text-text-muted">
                {r.anchorLabel}
              </span>
              <button
                type="button"
                aria-label="Dismiss pin"
                onClick={() => dismiss(r.pin.dismissible_id)}
                className="data-readout ml-auto cursor-pointer text-micro text-text-muted hover:text-text-primary"
              >
                ✕
              </button>
            </div>
            <p className="text-[12px] leading-snug text-text-secondary">
              {r.pin.line}
            </p>
            {r.target.kind !== "none" && (
              <button
                type="button"
                onClick={() => openTarget(r)}
                className="micro-caps mt-xs cursor-pointer text-text-muted hover:text-text-primary"
              >
                {r.target.kind === "playlist"
                  ? "OPEN PLAYLIST →"
                  : "OPEN ARTIST →"}
              </button>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
