"use client";

import { AnimatePresence, motion } from "motion/react";

interface RightDockProps {
  open: boolean;
  wide?: boolean;
  /** Header swatch color (playlist identity); omit for non-entity panels. */
  swatch?: string;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}

/**
 * The right dock: one panel at a time, docked over the live map — never a
 * modal, no backdrop, no focus trap (docked-panel rules 1–2). Stops 56px
 * above the viewport floor: the transport strip is sacred (rule 6).
 */
export function RightDock({
  open,
  wide = false,
  swatch,
  title,
  onClose,
  children,
}: RightDockProps) {
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          key={title}
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="absolute top-0 right-0 bottom-[56px] z-20 flex flex-col border-border-subtle border-l bg-surface-1"
          style={{ width: wide ? 640 : 440 }}
        >
          <header className="flex items-center gap-sm border-border-subtle border-b px-lg py-md">
            {swatch && (
              <span
                className="inline-block size-[10px] rounded-xs"
                style={{ background: swatch }}
              />
            )}
            <h2 className="display-caps text-micro text-text-secondary">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="data-readout ml-auto cursor-pointer text-sm text-text-muted hover:text-text-primary"
              aria-label="Close panel"
            >
              ESC
            </button>
          </header>
          <div className="flex min-h-0 flex-1 flex-col gap-lg overflow-y-auto p-lg">
            {children}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

/** Instrument readout: micro-caps label over a mono value. Never a KPI card. */
export function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-2xs">
      <span className="micro-caps text-text-muted">{label}</span>
      <span className="data-readout text-lg text-text-primary">{value}</span>
    </div>
  );
}

/** Designed pending state for analytics that the engine hasn't computed yet. */
export function NotYetComputed({ what }: { what: string }) {
  return (
    <div className="flex flex-col gap-2xs border border-border-subtle border-dashed rounded-md px-md py-sm">
      <span className="micro-caps text-text-muted">{what}</span>
      <span className="text-sm text-text-secondary">
        Not yet computed — the analytics engine hasn't run over this library.
      </span>
    </div>
  );
}
