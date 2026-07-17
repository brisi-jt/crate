"use client";

import { useEffect, useReducer } from "react";
import { toast } from "sonner";
import { Explain } from "@/components/explain/explain";
import { Button } from "@/components/ui/button";
import { useApplyFlowArc, useFlowArc } from "@/hooks/api/use-competitive";
import { useUndoJournal } from "@/hooks/api/use-journal";
import { usePlaylistTracks } from "@/hooks/api/use-playlist-tracks";
import { ApiError } from "@/lib/api/errors";
import type { FlowMood } from "@/lib/api/schemas-competitive";
import {
  arcReducer,
  buildArcRows,
  initialArcState,
  isPermutation,
} from "@/lib/competitive/flow-arc";

const MOODS: { value: FlowMood; label: string; hint: string }[] = [
  { value: "rising", label: "Rising", hint: "builds energy" },
  { value: "falling", label: "Falling", hint: "winds down" },
  { value: "peak", label: "Peak", hint: "rises then falls" },
];

/**
 * F4 — the flow sequencer. Pick a mood → preview a suggested order (current vs
 * suggested flow + adjacent-artist repeats) → apply (a journaled reorder) →
 * undo via the returned journal link. A concurrent edit staling the order
 * surfaces as a recoverable in-tab error, not a crash.
 */
export function FlowTab({ playlistId }: { playlistId: number }) {
  const [state, dispatch] = useReducer(arcReducer, initialArcState);
  // Preview fetches whenever the tab is mounted for the chosen mood.
  const arc = useFlowArc(playlistId, state.mood, true);
  const apply = useApplyFlowArc(playlistId);
  const undo = useUndoJournal();
  // First page of tracks — enough to map most moves to names for the preview.
  const tracks = usePlaylistTracks(playlistId, 0);

  // Feed the fetched preview into the state machine. Keyed on the fetched
  // mood so switching back to a cached mood (same data ref) still re-loads the
  // preview after setMood cleared it.
  useEffect(() => {
    if (arc.data && arc.data.mood === state.mood) {
      dispatch({ type: "loaded", preview: arc.data });
    } else if (arc.isError) {
      dispatch({
        type: "error",
        message:
          arc.error instanceof Error
            ? arc.error.message
            : "Couldn't compute a flow arc.",
      });
    }
  }, [arc.data, arc.isError, arc.error, state.mood]);

  const preview = state.preview;
  const currentTracks =
    tracks.data?.items.map((t) => ({
      track_id: t.track.id,
      name: t.track.name,
      artist: t.track.artists.map((a) => a.name).join(", "),
    })) ?? [];
  const currentIds = currentTracks.map((t) => t.track_id);

  const rows = preview
    ? buildArcRows(currentTracks, preview.suggested_order)
    : [];
  const movedRows = rows.filter((r) => r.moved);

  function handleApply() {
    if (!preview || preview.suggested_order.length === 0) return;
    dispatch({ type: "applying" });
    apply.mutate(preview.suggested_order, {
      onSuccess: (result) => {
        dispatch({ type: "applied" });
        toast("Re-sequenced the playlist", {
          duration: 8000,
          action: {
            label: "UNDO",
            onClick: () => undo.mutate(result.journal_id),
          },
        });
      },
      onError: (error) => {
        const stale =
          error instanceof ApiError &&
          (error.status === 409 || error.problem?.error_code === "ORDER_STALE");
        dispatch({
          type: "error",
          message: stale
            ? "The playlist changed since this preview — re-previewing."
            : error instanceof Error
              ? error.message
              : "Apply failed.",
        });
        // A stale order self-heals: refetch a fresh preview.
        if (stale) arc.refetch();
      },
    });
  }

  return (
    <div className="flex flex-col gap-lg">
      {/* Mood picker */}
      <div className="flex flex-col gap-xs">
        <Explain metric="flow_arc">
          <span className="micro-caps text-text-muted">Flow arc — shape</span>
        </Explain>
        <div className="flex flex-wrap gap-xs">
          {MOODS.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => dispatch({ type: "setMood", mood: m.value })}
              aria-pressed={state.mood === m.value}
              className={`flex flex-col items-start rounded-xs border px-sm py-2xs text-left ${
                state.mood === m.value
                  ? "border-amber text-amber"
                  : "border-border-subtle text-text-muted hover:text-text-secondary"
              }`}
            >
              <span className="micro-caps">{m.label}</span>
              <span className="text-micro text-text-muted">{m.hint}</span>
            </button>
          ))}
        </div>
      </div>

      {arc.isFetching && !preview && (
        <div className="h-[80px] animate-pulse rounded-md bg-surface-2" />
      )}

      {state.status === "error" && (
        <p className="text-sm text-danger">{state.error}</p>
      )}

      {preview && preview.suggested_order.length === 0 && (
        <p className="text-sm text-text-secondary">
          Too few tracks to re-sequence — the flow arc needs a handful of
          reorderable tracks.
        </p>
      )}

      {preview && preview.suggested_order.length > 0 && (
        <>
          {/* Flow before / after */}
          <div className="flex flex-wrap items-end gap-xl">
            <div className="flex flex-col gap-2xs">
              <span className="micro-caps text-text-muted">Flow now</span>
              <span className="data-readout text-lg text-text-primary">
                {preview.current_flow !== null
                  ? Math.round(preview.current_flow)
                  : "—"}
              </span>
            </div>
            <span className="pb-1 text-text-muted">→</span>
            <div className="flex flex-col gap-2xs">
              <span className="micro-caps text-text-muted">Suggested</span>
              <span className="data-readout text-lg text-amber">
                {preview.suggested_flow !== null
                  ? Math.round(preview.suggested_flow)
                  : "—"}
              </span>
            </div>
            <div className="flex flex-col gap-2xs">
              <span className="micro-caps text-text-muted">Artist repeats</span>
              <span className="data-readout text-lg text-text-primary">
                {preview.adjacent_artist_repeats}
              </span>
            </div>
          </div>

          {/* Sample of moves (resolvable on the first page) */}
          {movedRows.length > 0 && (
            <div className="flex flex-col gap-xs">
              <span className="micro-caps text-text-muted">
                Proposed order — moves
              </span>
              <div className="flex flex-col gap-2xs">
                {movedRows.slice(0, 10).map((r) => (
                  <div
                    key={r.track_id}
                    className="flex items-baseline gap-sm text-sm"
                  >
                    <span className="data-readout w-[64px] text-micro text-text-muted">
                      {String(r.currentPos).padStart(2, "0")} →{" "}
                      {String(r.suggestedPos).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-text-primary">
                      {r.name}
                      <span className="text-text-muted"> · {r.artist}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Apply */}
          <div className="flex items-center gap-sm">
            <Button
              size="sm"
              onClick={handleApply}
              disabled={
                state.status === "applying" ||
                !isPermutation(currentIds, preview.suggested_order) ||
                // Guard: only apply when we have the full roster to compare
                // against (page 1 = whole playlist for the common small case).
                currentIds.length !== preview.suggested_order.length
              }
              className="micro-caps"
            >
              {state.status === "applying" ? "Applying…" : "Apply this order"}
            </Button>
            {currentIds.length !== preview.suggested_order.length && (
              <span className="text-micro text-text-muted">
                Open the full track list to apply large reorders.
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
