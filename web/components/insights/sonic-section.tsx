"use client";

import { Explain } from "@/components/explain/explain";
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
          <Explain metric="camelot">
            <span className="micro-caps text-text-muted">Camelot keys</span>
          </Explain>
          <CamelotWheel camelot={sonic.camelot} />
        </div>
        <div className="flex flex-col gap-2xs">
          <Explain metric="mood_quadrants">
            <span className="micro-caps text-text-muted">
              Mood field — {sonic.mood.total.toLocaleString()} tracks
            </span>
          </Explain>
          <MoodQuadrants mood={sonic.mood} />
        </div>
      </div>

      <Separator />

      <div className="flex flex-col gap-2xs">
        <Explain metric="tempo_spine">
          <span className="micro-caps text-text-muted">Tempo — BPM spine</span>
        </Explain>
        <TempoHistogram tempo={sonic.tempo} />
      </div>

      <Separator />

      <div className="flex flex-col gap-2xs">
        <Explain metric="ridgelines">
          <span className="micro-caps text-text-muted">
            Feature distributions — shape, not mean
          </span>
        </Explain>
        <Ridgelines ridgelines={sonic.ridgelines} />
      </div>
    </div>
  );
}
