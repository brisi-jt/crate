"use client";

import { CamelotWheel } from "@/components/insights/camelot-wheel";
import { MoodQuadrants } from "@/components/insights/mood-quadrants";
import { Ridgelines } from "@/components/insights/ridgelines";
import { TempoHistogram } from "@/components/insights/tempo-histogram";
import { Separator } from "@/components/ui/separator";
import type { SonicSignatures } from "@/lib/api/schemas";

/**
 * SONIC SIGNATURES — the family that is dead for every competitor (Spotify's
 * Nov-2024 lockdown) and live here because crate computes its own features.
 * Camelot wheel + mood quadrants side by side, then the tempo spine and the
 * feature ridgelines.
 */
export function SonicSection({ sonic }: { sonic: SonicSignatures }) {
  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap items-start gap-xl">
        <div className="flex flex-col gap-2xs">
          <span className="micro-caps text-text-muted">Camelot keys</span>
          <CamelotWheel camelot={sonic.camelot} />
        </div>
        <div className="flex flex-col gap-2xs">
          <span className="micro-caps text-text-muted">
            Mood field — {sonic.mood.total.toLocaleString()} tracks
          </span>
          <MoodQuadrants mood={sonic.mood} />
        </div>
      </div>

      <Separator />

      <div className="flex flex-col gap-2xs">
        <span className="micro-caps text-text-muted">Tempo — BPM spine</span>
        <TempoHistogram tempo={sonic.tempo} />
      </div>

      <Separator />

      <div className="flex flex-col gap-2xs">
        <span className="micro-caps text-text-muted">
          Feature distributions — shape, not mean
        </span>
        <Ridgelines ridgelines={sonic.ridgelines} />
      </div>
    </div>
  );
}
