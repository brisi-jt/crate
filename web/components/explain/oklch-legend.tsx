"use client";

import { useState } from "react";
import { acousticColor, oklchString } from "@/lib/color/acoustic";

/**
 * The persistent colour legend — colour is the app's central claim (every dot
 * is its sound), so every canvas carries a quiet chip decoding it: hue =
 * organic↔electronic, chroma = energy, lightness = mood. Click expands the
 * three-axis key. Docks in a canvas corner, whisper-quiet.
 */

const HUE_STOPS = [0, 0.25, 0.5, 0.75, 1].map((e) =>
  oklchString(
    acousticColor({ acousticness: 1 - e, energy: 0.6, valence: 0.6 }),
  ),
);

interface OklchLegendProps {
  position?: "bottom-right" | "bottom-left" | "top-right" | "top-left";
}

const POSITION_CLASSES: Record<
  NonNullable<OklchLegendProps["position"]>,
  string
> = {
  "bottom-right": "bottom-[72px] right-lg",
  "bottom-left": "bottom-[72px] left-lg",
  "top-right": "top-[56px] right-lg",
  "top-left": "top-[56px] left-lg",
};

export function OklchLegend({ position = "bottom-right" }: OklchLegendProps) {
  const [open, setOpen] = useState(false);

  return (
    <div
      className={`pointer-events-auto absolute z-10 flex flex-col items-end gap-xs ${POSITION_CLASSES[position]}`}
    >
      {open && (
        <div className="w-[240px] rounded-sm border border-border-subtle bg-surface-1 p-md shadow-sm">
          <div className="mb-sm flex items-baseline justify-between">
            <span className="display-caps text-micro text-text-secondary">
              Colour = sound
            </span>
          </div>
          <div className="flex flex-col gap-sm">
            <LegendAxis
              label="Hue"
              body="organic ↔ electronic"
              ramp={
                <div
                  className="h-[6px] w-full rounded-xs"
                  style={{
                    background: `linear-gradient(90deg, ${HUE_STOPS.join(", ")})`,
                  }}
                />
              }
            />
            <LegendAxis label="Chroma" body="colour intensity = energy" />
            <LegendAxis label="Lightness" body="brightness = mood" />
          </div>
          <p className="mt-sm border-border-subtle border-t pt-sm text-[11px] leading-snug text-text-muted">
            Similar sound means similar colour. Traits come from ReccoBeats and
            Essentia, as your library's own percentiles.
          </p>
        </div>
      )}

      <button
        type="button"
        aria-expanded={open}
        aria-label={open ? "Hide colour legend" : "What do the colours mean?"}
        onClick={() => setOpen((v) => !v)}
        className="flex cursor-pointer items-center gap-xs rounded-sm border border-border-subtle bg-surface-1 px-sm py-2xs transition-colors hover:border-border-strong"
      >
        <span
          className="h-[8px] w-[36px] rounded-xs"
          style={{
            background: `linear-gradient(90deg, ${HUE_STOPS.join(", ")})`,
          }}
        />
        <span className="micro-caps text-text-muted">
          {open ? "COLOUR ?" : "COLOUR"}
        </span>
      </button>
    </div>
  );
}

function LegendAxis({
  label,
  body,
  ramp,
}: {
  label: string;
  body: string;
  ramp?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2xs">
      <div className="flex items-baseline justify-between gap-sm">
        <span className="micro-caps text-text-muted">{label}</span>
        <span className="text-[11px] text-text-secondary">{body}</span>
      </div>
      {ramp}
    </div>
  );
}
