"use client";

import type { ReactNode } from "react";

/**
 * Shared primitives for the extended-survey sections — a quiet explained empty
 * state, a labeled horizontal bar row, and a small delta strip. Kept tiny and
 * presentational; all logic lives in lib/insights/extended-view.ts.
 */

/**
 * A hushed pending state for a section whose source table is still empty. Some
 * of these tables only fill after the streaming-history import runs or after
 * radio/feedback accrues — so this reads as "not yet", never as an error.
 */
export function ExtendedEmpty({ note }: { note: string }) {
  return (
    <div className="flex flex-col gap-2xs rounded-md border border-border-subtle border-dashed px-md py-sm">
      <span className="micro-caps text-text-muted">Nothing here yet</span>
      <span className="max-w-[52ch] text-sm text-text-secondary">{note}</span>
    </div>
  );
}

/** A labeled bar row: name on the left, a proportional bar, a mono value. */
export function BarRow({
  label,
  fraction,
  value,
  accent = false,
}: {
  label: ReactNode;
  fraction: number;
  value: string;
  accent?: boolean;
}) {
  const pct = Math.min(100, Math.max(2, fraction * 100));
  return (
    <div className="flex items-center gap-sm">
      <span className="w-[150px] truncate text-sm text-text-primary">
        {label}
      </span>
      <div className="h-[4px] flex-1 rounded-xs bg-surface-2">
        <div
          className={`h-full rounded-xs ${accent ? "bg-accent-amber" : "bg-border-strong"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="data-readout w-[56px] text-right text-micro text-text-muted">
        {value}
      </span>
    </div>
  );
}

/**
 * A per-feature delta strip: each axis as a centered bar leaning left or right
 * from a midline. Used by the three fingerprint-delta insights (liked vs
 * playlist, sound of yes, top vs library).
 */
export function DeltaStrip({
  axes,
}: {
  axes: Array<{ feature: string; delta: number }>;
}) {
  const maxAbs = axes.reduce((m, a) => Math.max(m, Math.abs(a.delta)), 0) || 1;
  return (
    <div className="flex flex-col gap-2xs">
      {axes.map((a) => {
        const frac = a.delta / maxAbs; // -1..1
        const width = Math.abs(frac) * 50; // half-width percentage
        const positive = frac >= 0;
        return (
          <div key={a.feature} className="flex items-center gap-sm">
            <span className="w-[120px] truncate text-sm text-text-secondary">
              {a.feature}
            </span>
            <div className="relative h-[6px] flex-1 rounded-xs bg-surface-2">
              <div className="absolute inset-y-0 left-1/2 w-px bg-border-subtle" />
              <div
                className="absolute inset-y-0 rounded-xs bg-border-strong"
                style={
                  positive
                    ? { left: "50%", width: `${width}%` }
                    : { right: "50%", width: `${width}%` }
                }
              />
            </div>
            <span className="data-readout w-[52px] text-right text-micro text-text-muted">
              {a.delta >= 0 ? "+" : ""}
              {a.delta.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** A compact track/name line: primary title + muted subtitle + trailing mono. */
export function NameLine({
  title,
  subtitle,
  trailing,
}: {
  title: string;
  subtitle?: string;
  trailing?: string;
}) {
  return (
    <div className="flex items-baseline gap-sm">
      <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
        {title}
        {subtitle && <span className="text-text-muted"> · {subtitle}</span>}
      </span>
      {trailing && (
        <span className="data-readout shrink-0 text-micro text-text-muted">
          {trailing}
        </span>
      )}
    </div>
  );
}
