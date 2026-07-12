"use client";

import {
  useCompileEdition,
  useEdition,
  useEditions,
} from "@/hooks/api/use-insights";
import {
  editionBandState,
  editionLabel,
  type NarrativeTint,
  narrativeTint,
} from "@/lib/insights/editions";

/** Narrative-tint token → text color class. */
const TINT_CLASS: Record<NarrativeTint, string> = {
  amber: "text-amber",
  sage: "text-success",
  rose: "text-danger",
  neutral: "text-text-secondary",
};

/**
 * The field-journal band at the top of the survey — the latest edition's
 * narrative, framed as change (or as a first baseline reading for edition 1).
 * COMPILE NOW rebuilds this week on demand; weekly editions also compile on
 * the scheduler. Empty state prompts the first compile honestly.
 */
export function EditionBand() {
  const editions = useEditions();
  const compile = useCompileEdition();

  const state = editionBandState(editions.data?.items ?? []);
  const latestId = state.kind === "empty" ? null : state.latest.id;
  const edition = useEdition(latestId);

  return (
    <div className="flex flex-col gap-sm rounded-md border border-border-subtle bg-surface-2 p-md">
      <div className="flex items-baseline gap-sm">
        <span className="display-caps text-micro text-text-secondary">
          FIELD JOURNAL
        </span>
        {state.kind !== "empty" && (
          <span className="data-readout text-micro text-text-muted">
            {editionLabel(state.latest)}
          </span>
        )}
        <button
          type="button"
          onClick={() => compile.mutate()}
          disabled={compile.isPending}
          className="micro-caps ml-auto cursor-pointer text-text-muted hover:text-text-primary disabled:text-text-muted"
        >
          {compile.isPending ? "COMPILING…" : "COMPILE NOW"}
        </button>
      </div>

      {state.kind === "empty" ? (
        <p className="max-w-[60ch] text-sm text-text-secondary">
          No editions yet. Compile this week's reading to start the journal —
          the first edition is a baseline; later ones narrate what moved.
        </p>
      ) : edition.isPending ? (
        <span className="micro-caps text-text-muted">READING EDITION…</span>
      ) : edition.isError || !edition.data ? (
        <span className="micro-caps text-danger">EDITION UNAVAILABLE</span>
      ) : (
        <div className="flex flex-col gap-2xs">
          {state.kind === "baseline" && (
            <span className="micro-caps text-text-muted">
              Baseline reading — later editions will chart the drift.
            </span>
          )}
          {edition.data.narrative.map((line) => (
            <p
              key={line.text}
              className={`text-sm leading-snug ${TINT_CLASS[narrativeTint(line.kind)]}`}
            >
              {line.text}
            </p>
          ))}
        </div>
      )}

      {compile.isError && (
        <span className="micro-caps text-danger">
          COMPILE FAILED · TRY AGAIN
        </span>
      )}
    </div>
  );
}
