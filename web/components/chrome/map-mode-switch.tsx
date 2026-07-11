"use client";

import { useUiStore } from "@/lib/store/ui";

/**
 * Map mode chrome, alongside the sync readout: flips the canvas between the
 * playlist graph (force) and the track field (UMAP scatter), plus the
 * cluster-hull overlay toggle while the field is up. Same field-manual
 * switch pattern as FOLLOWED SHOWN/HIDDEN.
 */
export function MapModeSwitch() {
  const mapMode = useUiStore((s) => s.mapMode);
  const setMapMode = useUiStore((s) => s.setMapMode);
  const clusterOverlay = useUiStore((s) => s.clusterOverlay);
  const setClusterOverlay = useUiStore((s) => s.setClusterOverlay);
  const tracks = mapMode === "tracks";

  return (
    <div className="pointer-events-auto flex items-center gap-md">
      <button
        type="button"
        role="switch"
        aria-checked={tracks}
        onClick={() => setMapMode(tracks ? "playlists" : "tracks")}
        title="Flip between the playlist graph and the track field"
        className={`micro-caps cursor-pointer ${
          tracks
            ? "text-text-primary"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        VIEW {tracks ? "TRACK FIELD" : "PLAYLIST GRAPH"}
      </button>

      {tracks && (
        <button
          type="button"
          role="switch"
          aria-checked={clusterOverlay}
          onClick={() => setClusterOverlay(!clusterOverlay)}
          title="Density-cluster hulls under the points"
          className={`micro-caps cursor-pointer ${
            clusterOverlay
              ? "text-text-primary"
              : "text-text-muted hover:text-text-secondary"
          }`}
        >
          CLUSTERS {clusterOverlay ? "SHOWN" : "HIDDEN"}
        </button>
      )}
    </div>
  );
}
