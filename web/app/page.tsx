"use client";

import { useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Toaster } from "sonner";
import { CommandPalette } from "@/components/chrome/command-palette";
import { MapModeSwitch } from "@/components/chrome/map-mode-switch";
import { SyncReadout } from "@/components/chrome/sync-readout";
import { TransportStrip } from "@/components/chrome/transport-strip";
import { ListeningDeck } from "@/components/deck/listening-deck";
import type {
  FlyToRequest,
  GhostRender,
} from "@/components/graph/graph-canvas";
import {
  type ContextMenuState,
  NodeContextMenu,
} from "@/components/graph/node-context-menu";
import { BulkOpsPanelContent } from "@/components/panels/bulk-ops-panel";
import { LibraryStatsPanelContent } from "@/components/panels/library-stats-panel";
import { OpsLogPanelContent } from "@/components/panels/ops-log-panel";
import { PlaylistPanelContent } from "@/components/panels/playlist-panel";
import { RightDock } from "@/components/panels/right-dock";
import { TrackCardPanelContent } from "@/components/panels/track-card-panel";
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
import { nodeRadius } from "@/lib/graph/geometry";
import { useDeckStore } from "@/lib/store/deck";
import { useUiStore } from "@/lib/store/ui";

// The force graph needs the DOM — client-only, and all camera/ref logic
// stays inside the module so nothing crosses the dynamic boundary.
const GraphCanvas = dynamic(() => import("@/components/graph/graph-canvas"), {
  ssr: false,
});

const TrackField = dynamic(() => import("@/components/field/track-field"), {
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
  const openTrack = useUiStore((s) => s.openTrack);
  const mapMode = useUiStore((s) => s.mapMode);
  const setMapMode = useUiStore((s) => s.setMapMode);
  const closeRightPanel = useUiStore((s) => s.closeRightPanel);
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);
  const popLayer = useUiStore((s) => s.popLayer);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  const deckPlaylistId = useDeckStore((s) => s.playlistId);
  const closeDeck = useDeckStore((s) => s.close);
  const [ghost, setGhost] = useState<GhostRender | null>(null);
  const [flyTo, setFlyTo] = useState<FlyToRequest | null>(null);

  const flyToNode = useCallback((nodeId: number) => {
    setFlyTo((previous) => ({ nodeId, nonce: (previous?.nonce ?? 0) + 1 }));
  }, []);

  // Opening the deck flies the camera to the target playlist so the node and
  // its ghost stay visible above the deck card.
  useEffect(() => {
    if (deckPlaylistId !== null) flyToNode(deckPlaylistId);
  }, [deckPlaylistId, flyToNode]);

  // Keyboard layer control: ⌘K opens the palette, Escape pops one layer
  // top-down (context menu → palette → deck → right panel → the map, alone).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setPaletteOpen(!useUiStore.getState().paletteOpen);
      } else if (event.key === "Escape") {
        if (contextMenu) {
          setContextMenu(null);
        } else if (useUiStore.getState().paletteOpen) {
          setPaletteOpen(false);
        } else if (useDeckStore.getState().playlistId !== null) {
          closeDeck();
        } else {
          popLayer();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setPaletteOpen, popLayer, contextMenu, closeDeck]);

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

  const rightInset = rightPanel
    ? rightPanel.kind === "stats" || rightPanel.kind === "bulk-ops"
      ? 640
      : 440
    : 0;

  const deckNode = useMemo(
    () => nodes.find((n) => n.id === deckPlaylistId) ?? null,
    [nodes, deckPlaylistId],
  );
  const deckSwatch = deckNode
    ? oklchString(
        deckNode.centroid ? acousticColor(deckNode.centroid) : GREY_NODE,
      )
    : null;

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
        {graph.data && mapMode === "tracks" ? (
          <TrackField
            graph={graph.data}
            selectedTrackId={
              rightPanel?.kind === "track" ? rightPanel.trackId : null
            }
            onSelectTrack={(trackId) => {
              if (trackId === null) {
                if (rightPanel?.kind === "track") closeRightPanel();
              } else {
                openTrack(trackId);
              }
            }}
            rightInset={rightInset}
            reducedMotion={reducedMotion}
          />
        ) : graph.data ? (
          <GraphCanvas
            graph={graph.data}
            selectedId={selectedPlaylistId}
            onSelect={(id) =>
              id === null ? closeRightPanel() : openPlaylist(id)
            }
            onNodeContextMenu={(playlistId, x, y) =>
              setContextMenu({ playlistId, x, y })
            }
            rightInset={rightInset}
            reducedMotion={reducedMotion}
            dim={
              deckPlaylistId !== null
                ? { targetId: deckPlaylistId, ghost }
                : null
            }
            flyTo={flyTo}
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
        <div className="pointer-events-none absolute top-md left-lg z-10 flex items-center gap-md">
          <SyncReadout graph={graph.data ?? null} />
          {graph.data && <MapModeSwitch />}
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

      <RightDock
        open={rightPanel?.kind === "bulk-ops"}
        wide
        title="Bulk operation"
        onClose={closeRightPanel}
      >
        {rightPanel?.kind === "bulk-ops" && (
          <BulkOpsPanelContent initialSourceId={rightPanel.sourceId} />
        )}
      </RightDock>

      <RightDock
        open={rightPanel?.kind === "ops-log"}
        title="Operations log"
        onClose={closeRightPanel}
      >
        {rightPanel?.kind === "ops-log" && <OpsLogPanelContent />}
      </RightDock>

      <RightDock
        open={rightPanel?.kind === "track"}
        title="Track"
        onClose={closeRightPanel}
      >
        {rightPanel?.kind === "track" && (
          <TrackCardPanelContent
            trackId={rightPanel.trackId}
            onShowInGraph={(playlistId) => {
              setMapMode("playlists");
              openPlaylist(playlistId);
            }}
          />
        )}
      </RightDock>

      {contextMenu && (
        <NodeContextMenu
          menu={contextMenu}
          nodes={nodes}
          onClose={() => setContextMenu(null)}
        />
      )}

      {deckPlaylistId !== null && deckNode && (
        <ListeningDeck
          playlistId={deckPlaylistId}
          playlistName={deckNode.name}
          playlistSwatch={deckSwatch}
          targetRadius={nodeRadius(deckNode.track_count)}
          onGhostChange={setGhost}
          onClose={closeDeck}
        />
      )}

      <TransportStrip onArtworkClick={flyToNode} />

      <CommandPalette nodes={nodes} />

      {/* Undo toasts (tier-1 writes): bottom-left, clear of the transport. */}
      <Toaster
        position="bottom-left"
        offset={{ bottom: 72, left: 16 }}
        gap={8}
        toastOptions={{
          unstyled: false,
          style: {
            background: "var(--surface-3)",
            border: "1px solid var(--border-subtle)",
            color: "var(--text-primary)",
            fontFamily: "var(--font-b612)",
            fontSize: "13px",
            borderRadius: "6px",
          },
          actionButtonStyle: {
            background: "var(--accent-amber)",
            color: "var(--accent-ink)",
            fontFamily: "var(--font-b612-mono)",
            fontSize: "11px",
            letterSpacing: "0.08em",
          },
        }}
      />
    </main>
  );
}
