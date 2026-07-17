/**
 * F4 flow-sequencer preview → apply state machine (pure). The playlist panel's
 * FLOW tab drives this: pick a mood → fetch a preview → review the before/after
 * → apply (a journaled reorder) → undo via the journal link. A concurrent edit
 * can stale the order, so apply failures land in a recoverable error state that
 * keeps the mood but drops the preview (forcing a re-preview).
 */

import type { FlowArc, FlowMood } from "@/lib/api/schemas-competitive";

export type ArcStatus =
  | "idle" // no preview loaded
  | "previewing" // a preview is loaded, ready to apply
  | "applying" // apply in flight
  | "applied" // apply landed
  | "error"; // preview or apply failed (recoverable)

export interface ArcState {
  mood: FlowMood;
  status: ArcStatus;
  preview: FlowArc | null;
  error: string | null;
}

export const initialArcState: ArcState = {
  mood: "rising",
  status: "idle",
  preview: null,
  error: null,
};

export type ArcAction =
  | { type: "setMood"; mood: FlowMood }
  | { type: "loaded"; preview: FlowArc }
  | { type: "applying" }
  | { type: "applied" }
  | { type: "error"; message: string };

export function arcReducer(state: ArcState, action: ArcAction): ArcState {
  switch (action.type) {
    case "setMood":
      // A new mood invalidates the loaded order — a fresh preview must be fetched.
      return {
        ...state,
        mood: action.mood,
        preview: null,
        status: "idle",
        error: null,
      };
    case "loaded":
      return {
        ...state,
        preview: action.preview,
        status: "previewing",
        error: null,
      };
    case "applying":
      return { ...state, status: "applying", error: null };
    case "applied":
      return { ...state, status: "applied", preview: null, error: null };
    case "error":
      return { ...state, status: "error", error: action.message };
    default:
      return state;
  }
}

/** True when `candidate` is a re-ordering of exactly the ids in `base`. */
export function isPermutation(base: number[], candidate: number[]): boolean {
  if (base.length !== candidate.length) return false;
  const baseSet = new Set(base);
  if (baseSet.size !== base.length) return false; // dup guard
  return candidate.every((id) => baseSet.has(id));
}

export interface ArcRowTrack {
  track_id: number;
  name: string;
  artist: string;
}

export interface ArcRow {
  track_id: number;
  name: string;
  artist: string;
  /** 1-based position in the suggested order. */
  suggestedPos: number;
  /** 1-based position in the current order. */
  currentPos: number;
  moved: boolean;
}

/**
 * Build the before/after table: the suggested order, each row annotated with
 * where the track sits now vs where it would move. Suggested ids not present in
 * the current roster are dropped (defensive — a permutation should never carry
 * strangers, but the view must not crash if the API and roster briefly diverge).
 */
export function buildArcRows(
  currentOrder: ArcRowTrack[],
  suggestedOrder: number[],
): ArcRow[] {
  const byId = new Map(
    currentOrder.map((t, i) => [t.track_id, { track: t, pos: i + 1 }]),
  );
  const rows: ArcRow[] = [];
  suggestedOrder.forEach((id, idx) => {
    const found = byId.get(id);
    if (!found) return;
    const suggestedPos = idx + 1;
    rows.push({
      track_id: id,
      name: found.track.name,
      artist: found.track.artist,
      suggestedPos,
      currentPos: found.pos,
      moved: found.pos !== suggestedPos,
    });
  });
  return rows;
}
