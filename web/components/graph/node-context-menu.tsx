"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useUndoJournal } from "@/hooks/api/use-journal";
import { useAddTracks } from "@/hooks/api/use-mutations";
import type { GraphNode } from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

export interface ContextMenuState {
  playlistId: number;
  x: number;
  y: number;
}

interface NodeContextMenuProps {
  menu: ContextMenuState;
  nodes: GraphNode[];
  onClose: () => void;
}

/**
 * Right-click menu for a map node — manually positioned (the canvas has no
 * DOM triggers for shadcn's ContextMenu). Carries the tier-1 write path:
 * adding the playlist panel's selected tracks lands instantly with an undo
 * toast.
 */
export function NodeContextMenu({
  menu,
  nodes,
  onClose,
}: NodeContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const node = nodes.find((n) => n.id === menu.playlistId) ?? null;
  const selectedTracks = useUiStore((s) => s.selectedTracks);
  const openPlaylist = useUiStore((s) => s.openPlaylist);
  const openBulkOps = useUiStore((s) => s.openBulkOps);
  const clearTrackSelection = useUiStore((s) => s.clearTrackSelection);
  const addTracks = useAddTracks();
  const undo = useUndoJournal();

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    }
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [onClose]);

  if (!node) return null;

  const itemClass =
    "block w-full cursor-pointer px-md py-xs text-left text-sm text-text-secondary hover:bg-surface-2 hover:text-text-primary disabled:cursor-default disabled:text-text-muted disabled:hover:bg-transparent";

  function addSelection() {
    if (!node) return;
    const count = selectedTracks.length;
    const label = count === 1 ? selectedTracks[0].name : `${count} tracks`;
    addTracks.mutate(
      {
        playlistId: node.id,
        trackIds: selectedTracks.map((t) => t.trackId),
      },
      {
        onSuccess: (result) => {
          toast(`Added ${label} → ${node.name}`, {
            duration: 8000,
            action: {
              label: "UNDO",
              onClick: () => undo.mutate(result.journal_id),
            },
          });
          clearTrackSelection();
        },
        onError: (error) => {
          toast.error(error instanceof Error ? error.message : "Add failed");
        },
      },
    );
    onClose();
  }

  return (
    <div
      ref={ref}
      className="fixed z-40 w-[240px] rounded-md border border-border-subtle bg-surface-3 py-xs"
      style={{ left: menu.x, top: menu.y }}
    >
      <div className="micro-caps truncate px-md pt-2xs pb-xs text-text-muted">
        {node.name}
      </div>
      <button
        type="button"
        className={itemClass}
        onClick={() => {
          openPlaylist(node.id);
          onClose();
        }}
      >
        Open playlist
      </button>
      <button
        type="button"
        className={itemClass}
        disabled={selectedTracks.length === 0 || addTracks.isPending}
        onClick={addSelection}
      >
        {selectedTracks.length === 0
          ? "Add selection — none selected"
          : `Add ${selectedTracks.length} selected track${selectedTracks.length === 1 ? "" : "s"}`}
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => {
          openBulkOps(node.id);
          onClose();
        }}
      >
        Bulk operation from here
      </button>
    </div>
  );
}
