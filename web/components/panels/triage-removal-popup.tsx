"use client";

import { motion } from "motion/react";
import { useReducer } from "react";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
import { useUndoJournal } from "@/hooks/api/use-journal";
import { useTriageCleanup } from "@/hooks/api/use-triage";
import { ApiError } from "@/lib/api/errors";
import {
  type CleanupSong,
  cleanupBody,
  cleanupSelectedCount,
  initCleanup,
  reduceCleanup,
} from "@/lib/triage/cleanup";

/**
 * Post-apply removal confirmation. Every song starts UNCHECKED — removing from
 * the source is opt-in — with select all/none. Liked source unsaves; playlist
 * source removes from the playlist. Journaled + undoable.
 */
export function TriageRemovalPopup({
  source,
  sourcePlaylistId,
  songs,
  onClose,
}: {
  source: "liked" | "playlist";
  sourcePlaylistId: number | null;
  songs: CleanupSong[];
  onClose: () => void;
}) {
  const [state, dispatch] = useReducer(reduceCleanup, songs, initCleanup);
  const cleanup = useTriageCleanup();
  const undo = useUndoJournal();
  const selected = cleanupSelectedCount(state);

  const verb =
    source === "liked" ? "remove from Liked Songs" : "remove from the playlist";

  const confirm = () => {
    const body =
      source === "playlist" && sourcePlaylistId !== null
        ? cleanupBody(state, {
            source: "playlist",
            playlistId: sourcePlaylistId,
          })
        : cleanupBody(state, { source: "liked" });

    if (body === null) {
      onClose();
      return;
    }

    cleanup.mutate(body, {
      onSuccess: (result) => {
        const journalId = result.journal_id;
        toast(`Removed ${result.removed} from source.`, {
          action: { label: "UNDO", onClick: () => undo.mutate(journalId) },
        });
        onClose();
      },
      onError: (error) => {
        const code =
          error instanceof ApiError ? error.problem?.error_code : undefined;
        if (code === "MEMBERSHIP_STALE") {
          toast("Already gone from the source.");
          onClose();
          return;
        }
        toast.error(error instanceof Error ? error.message : "Removal failed");
      },
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 z-30 flex items-end bg-canvas/60 p-lg"
    >
      <motion.div
        initial={{ y: 16, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 16, opacity: 0 }}
        className="flex w-full flex-col gap-md rounded-md border border-border-strong bg-surface-2 p-lg shadow-lg"
      >
        <div className="flex flex-col gap-2xs">
          <span className="display-caps text-micro text-text-secondary">
            Filed — clean up the source?
          </span>
          <span className="text-micro text-text-muted">
            Choose which songs to {verb}. Nothing is removed unless you check
            it.
          </span>
        </div>

        <div className="flex items-center gap-md">
          <button
            type="button"
            onClick={() => dispatch({ type: "SELECT_ALL" })}
            className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
          >
            SELECT ALL
          </button>
          <button
            type="button"
            onClick={() => dispatch({ type: "SELECT_NONE" })}
            className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
          >
            SELECT NONE
          </button>
        </div>

        <div className="flex max-h-[200px] flex-col gap-2xs overflow-y-auto">
          {state.songs.map((song) => (
            <div
              key={song.trackId}
              className="flex items-center gap-sm rounded-sm px-2xs py-2xs hover:bg-surface-1"
            >
              <Checkbox
                id={`cleanup-${song.trackId}`}
                checked={state.checked[song.trackId] ?? false}
                onCheckedChange={() =>
                  dispatch({ type: "TOGGLE", trackId: song.trackId })
                }
                aria-label={`Remove ${song.name} from source`}
              />
              <label
                htmlFor={`cleanup-${song.trackId}`}
                className="cursor-pointer truncate text-sm text-text-secondary"
              >
                {song.name}
              </label>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-end gap-sm">
          <button
            type="button"
            onClick={onClose}
            className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
          >
            KEEP IN SOURCE
          </button>
          <button
            type="button"
            disabled={selected === 0 || cleanup.isPending}
            onClick={confirm}
            className="display-caps cursor-pointer rounded-sm bg-amber px-md py-xs text-amber-ink text-micro transition-colors hover:bg-amber-press disabled:cursor-default disabled:opacity-40"
          >
            {cleanup.isPending
              ? "Removing…"
              : `${verb.split(" ")[0].toUpperCase()} ${selected}`}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
