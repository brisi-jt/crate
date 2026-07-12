"use client";

import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

interface SurveySectionProps {
  /** Michroma micro-caps section heading. */
  title: string;
  /** Right-aligned mono summary readout (counts, etc.). */
  meta?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

/**
 * A collapsible survey section — the option-A page skeleton is a stack of
 * these. Header is a micro-caps disclosure row; the body lazily mounts only
 * while open so heavy viz doesn't render for collapsed sections. No card
 * nesting (principle 4) — sections separate by hairline + spacing.
 */
export function SurveySection({
  title,
  meta,
  defaultOpen = true,
  children,
}: SurveySectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="flex flex-col gap-sm border-border-subtle border-t pt-lg first:border-t-0 first:pt-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex cursor-pointer items-baseline gap-sm text-left"
      >
        <span className="data-readout text-micro text-text-muted">
          {open ? "▾" : "▸"}
        </span>
        <span className="display-caps text-sm text-text-secondary">
          {title}
        </span>
        {meta && (
          <span className="data-readout ml-auto text-micro text-text-muted">
            {meta}
          </span>
        )}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="body"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className="flex flex-col gap-md pt-2xs">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
