"use client";

import type { RunCounts } from "@/lib/deck/empty-state";
import { runSummary, runYieldedNothing } from "@/lib/deck/empty-state";

interface DeckEmptyStateProps {
  kind: "unsurveyed" | "reviewed";
  playlistName: string;
  running: boolean;
  result: (RunCounts & { errors?: string[] }) | null;
  failed: boolean;
  onRun: () => void;
}

/**
 * The deck with nothing to review — first open before any discovery pass
 * (verifier finding D3), or a fully-reviewed queue. Beacon pattern: one
 * amber action, field-manual explanation, progress + result readouts.
 */
export function DeckEmptyState({
  kind,
  playlistName,
  running,
  result,
  failed,
  onRun,
}: DeckEmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-md py-lg text-center">
      <span className="micro-caps text-text-secondary">
        {kind === "unsurveyed" ? "NO CANDIDATES QUEUED" : "QUEUE REVIEWED"}
      </span>
      <p className="max-w-[44ch] text-sm text-text-secondary">
        {kind === "unsurveyed"
          ? `Discovery hasn't surveyed ${playlistName} yet. A pass asks Last.fm and ReccoBeats for nearby tracks, screens out everything already in the library, and files what clears the bar here.`
          : "Every candidate has a verdict. Run another pass to survey for fresh material."}
      </p>

      <button
        type="button"
        onClick={onRun}
        disabled={running}
        className="display-caps cursor-pointer rounded-sm bg-amber px-lg py-sm text-amber-ink text-micro transition-colors duration-150 hover:bg-amber-press disabled:cursor-default disabled:opacity-45"
      >
        {running ? "Pass running…" : "Run discovery"}
      </button>

      {running && (
        <span className="micro-caps text-text-muted">
          SURVEYING SOURCES · GENERATE → RESOLVE → PREVIEW
        </span>
      )}

      {!running && failed && (
        <span className="micro-caps text-danger">
          DISCOVERY PASS FAILED · TRY AGAIN
        </span>
      )}

      {!running && result && (
        <div className="flex flex-col items-center gap-2xs">
          <span className="data-readout text-micro text-text-secondary">
            {runSummary(result)}
          </span>
          {runYieldedNothing(result) && (
            <span className="text-sm text-text-muted">
              Nothing new cleared the library filter this pass.
            </span>
          )}
          {result.errors && result.errors.length > 0 && (
            <span className="micro-caps text-text-muted">
              {result.errors.length} SOURCE{" "}
              {result.errors.length === 1 ? "ERROR" : "ERRORS"} ISOLATED
            </span>
          )}
        </div>
      )}
    </div>
  );
}
