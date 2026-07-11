"use client";

import { type MapMode, useUiStore } from "@/lib/store/ui";

const MODES: Array<{ mode: MapMode; label: string }> = [
  { mode: "playlists", label: "PLAYLIST GRAPH" },
  { mode: "tracks", label: "TRACK FIELD" },
  { mode: "artists", label: "ARTIST GALAXY" },
];

/**
 * Map mode chrome, alongside the sync readout: a segmented micro-caps
 * control across the canvas trinity — playlist graph (force), track field
 * (UMAP scatter), artist galaxy (force). The two-mode state-labeled switch
 * became a segmented control at three modes; the cluster-hull toggle still
 * appears only while the field is up.
 */
export function MapModeSwitch() {
  const mapMode = useUiStore((s) => s.mapMode);
  const setMapMode = useUiStore((s) => s.setMapMode);
  const clusterOverlay = useUiStore((s) => s.clusterOverlay);
  const setClusterOverlay = useUiStore((s) => s.setClusterOverlay);

  return (
    <div className="pointer-events-auto flex items-center gap-md">
      <div className="flex items-center gap-xs">
        <span className="micro-caps text-text-muted">VIEW</span>
        {MODES.map(({ mode, label }, index) => (
          <span key={mode} className="flex items-center gap-xs">
            {index > 0 && <span className="micro-caps text-text-muted">·</span>}
            <button
              type="button"
              aria-pressed={mapMode === mode}
              onClick={() => setMapMode(mode)}
              className={`micro-caps cursor-pointer ${
                mapMode === mode
                  ? "text-text-primary"
                  : "text-text-muted hover:text-text-secondary"
              }`}
            >
              {label}
            </button>
          </span>
        ))}
      </div>

      {mapMode === "tracks" && (
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
