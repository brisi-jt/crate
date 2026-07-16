"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import {
  type FieldGuideStats,
  fieldGuideContent,
} from "@/lib/field-guide/content";
import type { FieldGuideMode } from "@/lib/store/ui";
import { useUiStore } from "@/lib/store/ui";

interface FieldGuideCardProps {
  mode: FieldGuideMode;
  stats: FieldGuideStats;
  position?: "bottom-left" | "bottom-right" | "top-right" | "top-left";
  /**
   * "docked" (default) pins the card to a canvas corner. "inline" renders it
   * in normal flow — for panel surfaces where an absolute card would cover
   * the panel's own content.
   */
  variant?: "docked" | "inline";
}

const POSITION_CLASSES: Record<
  NonNullable<FieldGuideCardProps["position"]>,
  string
> = {
  "bottom-left": "bottom-[72px] left-lg",
  "bottom-right": "bottom-[72px] right-lg",
  "top-right": "top-[56px] right-lg",
  "top-left": "top-[56px] left-lg",
};

/**
 * Field guide for each canvas mode and the frontier panel. A micro-caps ?
 * affordance expands into a compact explainer card. Escape closes. First
 * visit per mode defaults to expanded.
 */
export function FieldGuideCard({
  mode,
  stats,
  position = "bottom-left",
  variant = "docked",
}: FieldGuideCardProps) {
  const fieldGuideExpanded = useUiStore((s) => s.fieldGuideExpanded);
  const fieldGuideFirstVisit = useUiStore((s) => s.fieldGuideFirstVisit);
  const setFieldGuideExpanded = useUiStore((s) => s.setFieldGuideExpanded);

  const hasVisited = fieldGuideFirstVisit[mode] === true;
  const expanded = hasVisited ? (fieldGuideExpanded[mode] ?? false) : true;

  const content = fieldGuideContent(mode, stats);

  // Escape closes the guide when expanded.
  // stopImmediatePropagation prevents the page-level popLayer handler from
  // also firing on the same keydown — in the frontier panel this would
  // otherwise collapse the guide AND pop the panel in one keystroke.
  // The listener is registered with `capture: true` so it runs before the
  // page-level bubble-phase listener and can suppress it reliably.
  useEffect(() => {
    if (!expanded) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopImmediatePropagation();
        setFieldGuideExpanded(mode, false);
      }
    }
    window.addEventListener("keydown", onKey, { capture: true });
    return () =>
      window.removeEventListener("keydown", onKey, { capture: true });
  }, [expanded, mode, setFieldGuideExpanded]);

  const wrapperClass =
    variant === "docked"
      ? `pointer-events-auto absolute z-10 flex flex-col items-start gap-xs ${POSITION_CLASSES[position]}`
      : "flex flex-col items-start gap-xs";

  return (
    <div className={wrapperClass}>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="guide-body"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className={`rounded-sm border border-border-subtle bg-surface-1 p-md shadow-sm ${
              variant === "docked" ? "w-[280px]" : "w-full"
            }`}
          >
            <div className="mb-sm flex items-baseline justify-between">
              <span className="display-caps text-micro text-text-secondary">
                {content.title}
              </span>
              <span className="data-readout text-micro text-text-muted">
                {content.summary}
              </span>
            </div>

            <div className="flex flex-col gap-xs">
              {content.legend.map((line) => (
                <div key={line.label} className="flex flex-col gap-2xs">
                  <span className="micro-caps text-text-muted">
                    {line.label}
                  </span>
                  <p className="text-[12px] leading-snug text-text-secondary">
                    {line.body}
                  </p>
                </div>
              ))}
            </div>

            {content.prompts.length > 0 && (
              <div className="mt-sm flex flex-col gap-2xs border-border-subtle border-t pt-sm">
                {content.prompts.map((prompt) => (
                  <p
                    key={prompt}
                    className="text-[11px] leading-snug text-text-muted"
                  >
                    {prompt}
                  </p>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <button
        type="button"
        aria-expanded={expanded}
        aria-label={expanded ? "Hide field guide" : "What am I looking at?"}
        onClick={() => setFieldGuideExpanded(mode, !expanded)}
        className={`micro-caps cursor-pointer transition-colors ${
          expanded
            ? "text-text-secondary hover:text-text-primary"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        {expanded ? "HIDE ?" : "?"}
      </button>
    </div>
  );
}
