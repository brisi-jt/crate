"use client";

import { useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Readout } from "@/components/panels/right-dock";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { resolveExplain } from "@/lib/explain/glossary";
import {
  explainTriggerGlyph,
  explainTriggerLabel,
} from "@/lib/explain/trigger";

/**
 * The one what/how/source affordance. Fed by the central glossary; the same
 * `metric` key resolves the same explanation everywhere.
 *
 * Two render modes, one content source:
 *  - variant="dom"    — a hushed `?` glyph beside a label, hover/focus opens a
 *    HoverCard. Keyboard-accessible; respects reduced motion.
 *  - variant="canvas" — a coordinate-anchored card for painted surfaces
 *    (nodes, axes, wheel wedges) that can't host a Radix trigger.
 */

interface ExplainDomProps {
  metric: string;
  variant?: "dom";
  children: ReactNode;
}

interface ExplainCanvasProps {
  metric: string;
  variant: "canvas";
  /** Anchor point in container-local coordinates. */
  x: number;
  y: number;
  /** Container width, so the card never spills off the right edge. */
  containerWidth: number;
}

type ExplainProps = ExplainDomProps | ExplainCanvasProps;

/** Shared body: term, then the three labeled parts. */
function ExplainBody({ metric }: { metric: string }) {
  const entry = resolveExplain(metric);
  if (!entry) return null;
  return (
    <div className="flex flex-col gap-sm">
      <div className="flex items-baseline justify-between gap-sm">
        <span className="display-caps text-micro text-text-secondary">
          {entry.term}
        </span>
        {entry.unit && (
          <span className="data-readout text-micro text-text-muted">
            {entry.unit}
          </span>
        )}
      </div>
      <p className="text-[12px] leading-snug text-text-secondary">
        {entry.what}
      </p>
      <div className="flex flex-col gap-2xs">
        <span className="micro-caps text-text-muted">How</span>
        <p className="text-[12px] leading-snug text-text-secondary">
          {entry.how}
        </p>
      </div>
      <div className="flex flex-col gap-2xs border-border-subtle border-t pt-sm">
        <span className="micro-caps text-text-muted">Source</span>
        <p className="text-[11px] leading-snug text-text-muted">
          {entry.source}
        </p>
      </div>
    </div>
  );
}

export function Explain(props: ExplainProps) {
  const prefersReduced = useReducedMotion() ?? false;

  if (props.variant === "canvas") {
    const { metric, x, y, containerWidth } = props;
    const entry = resolveExplain(metric);
    if (!entry) return null;
    const cardWidth = 280;
    const left = Math.min(x + 14, containerWidth - cardWidth - 12);
    return (
      <div
        role="tooltip"
        className="pointer-events-none absolute z-20 rounded-sm border border-border-subtle bg-surface-1 p-md shadow-sm"
        style={{ left: Math.max(12, left), top: y + 14, width: cardWidth }}
      >
        <ExplainBody metric={metric} />
      </div>
    );
  }

  const { metric, children } = props;
  const entry = resolveExplain(metric);

  // Unknown ref → render children bare, no dangling affordance.
  if (!entry) return <>{children}</>;

  return (
    <span className="inline-flex items-center gap-2xs">
      {children}
      <HoverCard>
        <HoverCardTrigger asChild>
          <button
            type="button"
            aria-label={explainTriggerLabel(metric)}
            className="micro-caps cursor-help rounded-xs px-2xs text-text-muted leading-none transition-colors hover:text-text-secondary focus-visible:text-text-secondary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
          >
            {explainTriggerGlyph()}
          </button>
        </HoverCardTrigger>
        <HoverCardContent
          // Reduced motion: Radix still portals the card; we drop the
          // data-driven CSS animation so it appears without motion.
          className={
            prefersReduced
              ? ""
              : "motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:animate-in motion-safe:duration-150"
          }
        >
          <ExplainBody metric={metric} />
        </HoverCardContent>
      </HoverCard>
    </span>
  );
}

/**
 * Convenience wrapper for the 40+ `Readout` sites: an instrument readout with
 * an explain `?` on its label. Adopt with one prop.
 */
export function ExplainReadout({
  metric,
  label,
  value,
}: {
  metric: string;
  label: string;
  value: string;
}) {
  return (
    <Explain metric={metric}>
      <Readout label={label} value={value} />
    </Explain>
  );
}
