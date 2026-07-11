/**
 * Deck body-state derivation — pure, so the first-open experience (empty
 * queue vs reviewed queue vs load failure) is testable without a DOM.
 */

export type DeckPhase =
  | "loading"
  | "error"
  | "card"
  | "unsurveyed"
  | "reviewed";

export interface DeckPhaseInput {
  /** Suggestions query still on its first load. */
  pending: boolean;
  /** Suggestions query failed. */
  failed: boolean;
  /** Candidates the queue returned (before review-machine removal). */
  itemCount: number;
  /** A candidate is under review right now. */
  hasCurrent: boolean;
}

export function deckPhase(input: DeckPhaseInput): DeckPhase {
  if (input.pending) return "loading";
  if (input.failed) return "error";
  if (input.hasCurrent) return "card";
  return input.itemCount === 0 ? "unsurveyed" : "reviewed";
}

export interface RunCounts {
  generated_lastfm: number;
  generated_reccobeats: number;
  resolved: number;
  previews_resolved: number;
}

/** Field-manual readout of a finished discovery pass. */
export function runSummary(counts: RunCounts): string {
  const generated = counts.generated_lastfm + counts.generated_reccobeats;
  return `GENERATED ${generated} · RESOLVED ${counts.resolved} · PREVIEWS ${counts.previews_resolved}`;
}

/** A pass that produced nothing reviewable gets an explanation, not silence. */
export function runYieldedNothing(counts: RunCounts): boolean {
  return counts.resolved === 0;
}
