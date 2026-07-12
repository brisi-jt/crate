"use client";

import { type RefObject, useEffect } from "react";
import type { ForceGraphMethods } from "react-force-graph-2d";
import {
  classifyWheelEvent,
  normaliseDelta,
  panDelta,
  zoomFactor,
} from "./wheel";

const MIN_ZOOM = 0.05;
const MAX_ZOOM = 20;

/**
 * Attaches a non-passive wheel listener to the canvas container.
 *
 * Discriminates between:
 *   - ctrlKey (trackpad pinch or Ctrl+scroll) → zoom centred on cursor
 *   - plain scroll (two-finger swipe or mouse wheel) → pan camera
 *
 * The listener is non-passive so it can call preventDefault() and prevent
 * the browser from intercepting the scroll event for its own pan/zoom.
 *
 * This hook should be used alongside enableZoomInteraction={false} on the
 * ForceGraph2D component so the library's own wheel handler does not also
 * fire and fight with this one.
 */
export function useCanvasWheel<N, L>(
  containerRef: RefObject<HTMLDivElement | null>,
  fgRef: RefObject<ForceGraphMethods<N, L> | undefined>,
) {
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function onWheel(e: WheelEvent) {
      e.preventDefault();

      const fg = fgRef.current;
      if (!fg) return;

      const dx = normaliseDelta(e.deltaX, e.deltaMode);
      const dy = normaliseDelta(e.deltaY, e.deltaMode);
      const kind = classifyWheelEvent(e.ctrlKey);

      if (kind === "zoom") {
        const k = fg.zoom() ?? 1;
        const factor = zoomFactor(dy);
        const newK = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, k * factor));
        fg.zoom(newK, 0);
      } else {
        const k = fg.zoom() ?? 1;
        const center = fg.centerAt();
        if (!center) return;
        fg.centerAt(center.x + panDelta(dx, k), center.y + panDelta(dy, k), 0);
      }
    }

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
    };
  }, [containerRef, fgRef]);
}
