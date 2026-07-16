"use client";

import { useEffect, useRef } from "react";
import type { NodeObject } from "react-force-graph-2d";
import {
  DRIFT_AMPLITUDE,
  driftOffset,
  driftPhase,
  shouldStepDrift,
} from "./breath";

/**
 * Own-RAF ambient breath: drives node positions with a deterministic sine
 * drift, independent of d3's alpha lifecycle.
 *
 * Why not a d3 force: the simulation stops ticking meaningfully once its alpha
 * settles, and a burst of camera interaction drives it into a local minimum
 * that reheats cannot escape — so a velocity-jitter force nets to sub-pixel and
 * the graph looks frozen. This loop instead waits for the layout to settle,
 * captures each node's rest position, then pins (fx/fy) every node to
 * `rest + driftOffset(now)` on its own ~30fps loop. d3 honours fx/fy verbatim
 * (node.x = node.fx each tick), so the drift survives settle, reheats, and
 * every pan/zoom/drag. The library's redraw loop (kept alive by
 * cooldownTime=Infinity) paints the updated positions.
 *
 * Reduced motion: the loop never starts; the layout settles into a still chart.
 *
 * @param nodes        - the live node array (same objects d3 mutates).
 * @param enabled      - false under reduced motion or before the graph mounts.
 * @param settleDelayMs- wait this long after (re)mount before capturing rest
 *                       positions, so the initial layout has spread first.
 * @returns a setter the canvas calls with the dragged node's id (or null) to
 *          suspend drift on that node during a drag.
 */
export function useBreathDrift<N extends NodeObject>(
  nodes: N[],
  enabled: boolean,
  settleDelayMs = 1400,
) {
  // Id of a node the user is actively dragging — drift is suspended for it so
  // it does not fight the drag (the library owns its fx/fy meanwhile).
  const draggingId = useRef<string | number | null>(null);

  // Exposed so the canvas can report drag state into the loop.
  const setDragging = useRef((id: string | number | null) => {
    draggingId.current = id;
  });

  useEffect(() => {
    if (!enabled) return;

    let raf = 0;
    let lastStep = 0;
    let rest: Map<
      string | number,
      { x: number; y: number; phase: number }
    > | null = null;
    const captureAt = performance.now() + settleDelayMs;

    const step = (now: number) => {
      raf = requestAnimationFrame(step);

      // Capture rest positions once the layout has had time to settle.
      if (rest === null) {
        if (now < captureAt) return;
        const settled = nodes.every(
          (n) => n.x !== undefined && n.y !== undefined,
        );
        if (!settled) return;
        rest = new Map();
        for (const n of nodes) {
          if (n.id === undefined) continue;
          rest.set(n.id, {
            x: n.x as number,
            y: n.y as number,
            phase: driftPhase(n.id),
          });
        }
      }

      if (!shouldStepDrift(now, lastStep)) return;
      lastStep = now;

      for (const n of nodes) {
        if (n.id === undefined || n.id === draggingId.current) continue;
        const r = rest.get(n.id);
        if (!r) continue;
        const { dx, dy } = driftOffset(now, r.phase, DRIFT_AMPLITUDE);
        // Hard-pin: d3 sets node.x = node.fx every tick, so this is the sole
        // authority over position and cannot be undone by the simulation.
        n.fx = r.x + dx;
        n.fy = r.y + dy;
      }
    };

    raf = requestAnimationFrame(step);

    return () => {
      cancelAnimationFrame(raf);
      // Release the pins so the layout is free again if drift is re-enabled or
      // the graph re-renders — leaving stale fx/fy would freeze nodes at their
      // last drifted spot.
      for (const n of nodes) {
        n.fx = undefined;
        n.fy = undefined;
      }
    };
    // fgRef is a stable ref and is not read in the loop (nodes are pinned
    // directly), so it is intentionally excluded from the dependency list.
  }, [nodes, enabled, settleDelayMs]);

  return setDragging.current;
}
