"use client";

import { useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import { useEffect, useMemo } from "react";
import { CommandPalette } from "@/components/chrome/command-palette";
import { SyncReadout } from "@/components/chrome/sync-readout";
import { TransportStrip } from "@/components/chrome/transport-strip";
import { LibraryStatsPanelContent } from "@/components/panels/library-stats-panel";
import { PlaylistPanelContent } from "@/components/panels/playlist-panel";
import { RightDock } from "@/components/panels/right-dock";
import {
  ConnectBeacon,
  FirstSyncBeacon,
  MapError,
  MapNotComputed,
  SyncInProgress,
} from "@/components/states/map-states";
import { useGraph } from "@/hooks/api/use-graph";
import { useSyncStatus, useTriggerSync } from "@/hooks/api/use-sync";
import { acousticColor, GREY_NODE, oklchString } from "@/lib/color/acoustic";
import { useUiStore } from "@/lib/store/ui";

// The force graph needs the DOM — client-only, and all camera/ref logic
// stays inside the module so nothing crosses the dynamic boundary.
const GraphCanvas = dynamic(() => import("@/components/graph/graph-canvas"), {
  ssr: false,
});

export default function MapPage() {
  const graph = useGraph();
  const status = useSyncStatus();
  const sync = useTriggerSync();
  const reducedMotion = useReducedMotion() ?? false;

  const rightPanel = useUiStore((s) => s.rightPanel);
  const selectedPlaylistId = useUiStore((s) => s.selectedPlaylistId);
  const openPlaylist = useUiStore((s) => s.openPlaylist);
  const closeRightPanel = useUiStore((s) => s.closeRightPanel);
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);
  const popLayer = useUiStore((s) => s.popLayer);

  // Keyboard layer control: ⌘K opens the palette, Escape pops one layer
  // top-down (palette → right panel → the map, alone).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setPaletteOpen(!useUiStore.getState().paletteOpen);
      } else if (event.key === "Escape") {
        popLayer();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setPaletteOpen, popLayer]);

  const nodes = useMemo(() => graph.data?.nodes ?? [], [graph.data]);
  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedPlaylistId) ?? null,
    [nodes, selectedPlaylistId],
  );
  const selectedSwatch = selectedNode
    ? oklchString(
        selectedNode.centroid
          ? acousticColor(selectedNode.centroid)
          : GREY_NODE,
      )
    : null;

  const rightInset = rightPanel ? (rightPanel.kind === "stats" ? 640 : 440) : 0;

  const showConnectBeacon =
    !graph.data && status.data && !status.data.spotify_connected;
  const showFirstSyncBeacon =
    !graph.data &&
    status.data?.spotify_connected &&
    !status.data.needs_reauth &&
    status.data.playlist_count === 0;

  return (
    <main className="fixed inset-0 overflow-hidden bg-canvas">
      {/* The map region — everything else docks over it */}
      <div className="absolute inset-x-0 top-0 bottom-[56px]">
        {graph.data ? (
          <GraphCanvas
            graph={graph.data}
            selectedId={selectedPlaylistId}
            onSelect={(id) =>
              id === null ? closeRightPanel() : openPlaylist(id)
            }
            rightInset={rightInset}
            reducedMotion={reducedMotion}
          />
        ) : graph.isPending || sync.isPending ? (
          <SyncInProgress />
        ) : graph.isError ? (
          <MapError
            message={
              graph.error instanceof Error
                ? graph.error.message
                : "Something went wrong loading the map."
            }
            onRetry={() => graph.refetch()}
          />
        ) : showConnectBeacon ? (
          <ConnectBeacon />
        ) : showFirstSyncBeacon ? (
          <FirstSyncBeacon
            onSync={() => sync.mutate()}
            syncing={sync.isPending}
          />
        ) : (
          <MapNotComputed />
        )}

        {/* Chrome woven onto the canvas margin — no bar, no card */}
        <div className="pointer-events-none absolute top-md left-lg z-10">
          <SyncReadout graph={graph.data ?? null} />
        </div>
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="micro-caps pointer-events-auto absolute top-md right-lg z-10 cursor-pointer text-text-muted hover:text-text-secondary"
        >
          ⌘K PALETTE
        </button>
      </div>

      <RightDock
        open={rightPanel?.kind === "playlist"}
        swatch={selectedSwatch ?? undefined}
        title={`Playlist — ${selectedNode?.name ?? ""}`}
        onClose={closeRightPanel}
      >
        {rightPanel?.kind === "playlist" && (
          <PlaylistPanelContent
            playlistId={rightPanel.playlistId}
            node={selectedNode}
            swatch={selectedSwatch}
          />
        )}
      </RightDock>

      <RightDock
        open={rightPanel?.kind === "stats"}
        wide
        title="Library stats"
        onClose={closeRightPanel}
      >
        {rightPanel?.kind === "stats" && <LibraryStatsPanelContent />}
      </RightDock>

      <TransportStrip />

      <CommandPalette nodes={nodes} />
    </main>
  );
}
