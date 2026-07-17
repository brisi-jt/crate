"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef } from "react";
import { Explain } from "@/components/explain/explain";
import { usePinCandidates } from "@/hooks/api/use-extended-insights";
import { samplePins } from "@/lib/pins/sampler";
import { usePinsStore } from "@/lib/store/pins";

const MAX_VISIBLE = 3;

/**
 * The variety layer for the insights page — a small, rotating strip of pinned
 * readings sampled client-side from the wide candidate pool. The sample is
 * seeded per session (stable within a session, fresh on "shuffle"), obeys a
 * one-per-family quota, favours strong readings, and down-weights ones seen in
 * recent sessions. Each pin's number carries its own what/how/source explain.
 */
export function ExtendedPinStrip() {
  const candidates = usePinCandidates("insights");
  const seed = usePinsStore((s) => s.seed);
  const hidden = usePinsStore((s) => s.hidden);
  const dismissed = usePinsStore((s) => s.dismissed);
  const shownHistory = usePinsStore((s) => s.shownHistory);
  const dismiss = usePinsStore((s) => s.dismiss);
  const reshuffle = usePinsStore((s) => s.reshuffle);
  const recordShown = usePinsStore((s) => s.recordShown);

  const dismissedSet = useMemo(() => new Set(dismissed), [dismissed]);

  // Freeze the shown-history at sample time so recording new shows (which
  // mutates shownHistory) doesn't resample and loop. The weighting reflects the
  // history as it stood when this seed's sample was drawn.
  const frozenHistory = useRef(shownHistory);
  const pool = candidates.data?.candidates;
  // Re-freeze whenever the seed or pool changes — i.e. a fresh sample is due.
  // biome-ignore lint/correctness/useExhaustiveDependencies: seed/pool are the resample triggers; shownHistory is intentionally read as a live snapshot, not a dependency.
  useMemo(() => {
    frozenHistory.current = usePinsStore.getState().shownHistory;
  }, [seed, pool]);

  const shown = useMemo(() => {
    return samplePins({
      candidates: pool ?? [],
      seed,
      dismissed: dismissedSet,
      shownHistory: frozenHistory.current,
      maxVisible: MAX_VISIBLE,
    });
  }, [pool, seed, dismissedSet]);

  // Record which pins were shown, exactly once per drawn seed, so future
  // sessions rotate away from them. Guarded by a last-recorded-seed ref so a
  // re-render never double-counts, and never feeds back into sampling.
  const recordedSeed = useRef<number | null>(null);
  useEffect(() => {
    if (recordedSeed.current === seed) return;
    const ids = shown.map((p) => p.dismissible_id);
    if (ids.length === 0) return;
    recordedSeed.current = seed;
    recordShown(ids);
  }, [seed, shown, recordShown]);

  if (hidden || candidates.isPending || shown.length === 0) return null;

  return (
    <div className="flex flex-col gap-xs rounded-md border border-border-subtle bg-surface-1 p-md">
      <div className="flex items-baseline justify-between gap-sm">
        <span className="micro-caps text-text-muted">Readings for you</span>
        <button
          type="button"
          onClick={reshuffle}
          className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
        >
          ⟳ Shuffle
        </button>
      </div>
      <AnimatePresence initial={false}>
        {shown.map((pin) => (
          <motion.div
            key={pin.dismissible_id}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="flex items-start gap-sm border-border-subtle border-t pt-xs first:border-t-0 first:pt-0"
          >
            <Explain metric={pin.metric_ref}>
              <span className="micro-caps text-text-muted">{pin.family}</span>
            </Explain>
            <p className="flex-1 text-[12px] leading-snug text-text-secondary">
              {pin.line}
            </p>
            <button
              type="button"
              aria-label="Dismiss reading"
              onClick={() => dismiss(pin.dismissible_id)}
              className="data-readout cursor-pointer text-micro text-text-muted hover:text-text-primary"
            >
              ✕
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
