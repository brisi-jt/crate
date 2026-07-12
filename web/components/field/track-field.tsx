"use client";

import { useMemo, useState } from "react";
import { FieldGuideCard } from "@/components/chrome/field-guide-card";
import type { FieldRenderPoint } from "@/components/field/track-field-canvas";
import TrackFieldCanvas from "@/components/field/track-field-canvas";
import { useMembershipIndex } from "@/hooks/api/use-membership";
import { useTrackMap } from "@/hooks/api/use-track-map";
import type { GraphResponse } from "@/lib/api/schemas";
import type { AcousticCentroid } from "@/lib/color/acoustic";
import {
  acousticColor,
  GREY_NODE,
  oklchString,
  selectionRing,
} from "@/lib/color/acoustic";
import { pointColor } from "@/lib/field/color";
import { clusterHulls, scalePositions } from "@/lib/field/layout";
import { useUiStore } from "@/lib/store/ui";

interface TrackFieldProps {
  graph: GraphResponse;
  selectedTrackId: number | null;
  onSelectTrack: (trackId: number | null) => void;
  rightInset: number;
  reducedMotion: boolean;
}

/**
 * The track field view: every enriched track at its UMAP position, colored
 * by the acoustic mapping, with a playlist legend that tints memberships.
 * The membership join runs client-side (the map payload has no playlist ids
 * yet) — points tint in as rosters load.
 */
export default function TrackField({
  graph,
  selectedTrackId,
  onSelectTrack,
  rightInset,
  reducedMotion,
}: TrackFieldProps) {
  const trackMap = useTrackMap();
  const clusterOverlay = useUiStore((s) => s.clusterOverlay);
  const selectedPlaylistId = useUiStore((s) => s.selectedPlaylistId);

  const [hoverPlaylistId, setHoverPlaylistId] = useState<number | null>(null);
  const [pinnedPlaylistId, setPinnedPlaylistId] = useState<number | null>(null);

  const playlistIds = useMemo(
    () => graph.nodes.map((n) => n.id),
    [graph.nodes],
  );
  const membership = useMembershipIndex(playlistIds, true);

  const centroidById = useMemo(() => {
    const map = new Map<number, AcousticCentroid | null>();
    for (const n of graph.nodes) map.set(n.id, n.centroid);
    return map;
  }, [graph.nodes]);

  const points = useMemo<FieldRenderPoint[]>(() => {
    const raw = trackMap.data?.points ?? [];
    const scaled = scalePositions(raw);
    return raw.map((p, i) => {
      const owners = p.playlist_ids ?? membership.byTrack.get(p.track_id) ?? [];
      const color = pointColor(
        p.features ?? null,
        owners.map((id) => centroidById.get(id) ?? null),
      );
      return {
        id: p.track_id,
        name: p.name,
        artist: p.artist,
        cluster: p.cluster,
        x: scaled[i].x,
        y: scaled[i].y,
        fill: oklchString(color),
        ring: oklchString(selectionRing(color)),
        grey: color === GREY_NODE,
      };
    });
  }, [trackMap.data, membership.byTrack, centroidById]);

  const hulls = useMemo(
    () => (clusterOverlay ? clusterHulls(points) : null),
    [clusterOverlay, points],
  );

  // Legend hover previews; a click pins; a playlist selected elsewhere
  // (palette jump, panel) highlights too. Multi-playlist tracks light up for
  // any playlist that holds them (union semantics).
  const activePlaylistId =
    hoverPlaylistId ?? pinnedPlaylistId ?? selectedPlaylistId;
  const highlightIds = useMemo(() => {
    if (activePlaylistId === null) return null;
    const ids = membership.byPlaylist.get(activePlaylistId);
    return ids ? new Set(ids) : new Set<number>();
  }, [activePlaylistId, membership.byPlaylist]);

  if (trackMap.isPending) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="micro-caps text-text-muted">
          PROJECTING TRACKS · FIRST PASS CAN TAKE A MOMENT
        </span>
      </div>
    );
  }

  if (trackMap.isError) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-xs">
        <span className="micro-caps text-danger">TRACK FIELD UNAVAILABLE</span>
        <button
          type="button"
          onClick={() => trackMap.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!trackMap.data || trackMap.data.points.length === 0) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-xs">
        <span className="micro-caps text-text-muted">FIELD NOT COMPUTED</span>
        <p className="max-w-[46ch] text-center text-sm text-text-secondary">
          The projection needs enriched tracks. It builds after enrichment has
          features to place — check back once coverage climbs.
        </p>
      </div>
    );
  }

  return (
    <div className="absolute inset-0">
      <TrackFieldCanvas
        points={points}
        hulls={hulls}
        highlightIds={highlightIds}
        selectedId={selectedTrackId}
        onSelect={onSelectTrack}
        rightInset={rightInset}
        reducedMotion={reducedMotion}
      />

      {/* Playlist legend — hover previews, click pins the tint. */}
      <div className="pointer-events-auto absolute top-[56px] left-lg z-10 flex w-[220px] flex-col gap-2xs">
        <div className="flex items-baseline justify-between">
          <span className="micro-caps text-text-muted">PLAYLISTS</span>
          {pinnedPlaylistId !== null && (
            <button
              type="button"
              onClick={() => setPinnedPlaylistId(null)}
              className="micro-caps cursor-pointer text-text-muted hover:text-text-secondary"
            >
              CLEAR
            </button>
          )}
        </div>
        <div className="flex max-h-[50vh] flex-col overflow-y-auto">
          {[...graph.nodes]
            .sort((a, b) => b.track_count - a.track_count)
            .map((node) => {
              const active = node.id === activePlaylistId;
              return (
                <button
                  key={node.id}
                  type="button"
                  onMouseEnter={() => setHoverPlaylistId(node.id)}
                  onMouseLeave={() => setHoverPlaylistId(null)}
                  onClick={() =>
                    setPinnedPlaylistId((prev) =>
                      prev === node.id ? null : node.id,
                    )
                  }
                  className={`flex cursor-pointer items-center gap-xs rounded-xs px-2xs py-[3px] text-left ${
                    active ? "bg-surface-2" : "hover:bg-surface-1"
                  }`}
                >
                  <span
                    className="inline-block size-[8px] flex-none rounded-xs"
                    style={{
                      background: oklchString(
                        node.centroid
                          ? acousticColor(node.centroid)
                          : GREY_NODE,
                      ),
                    }}
                  />
                  <span
                    className={`truncate text-sm ${
                      active ? "text-text-primary" : "text-text-secondary"
                    }`}
                  >
                    {node.name}
                  </span>
                  <span className="data-readout ml-auto text-micro text-text-muted">
                    {node.track_count}
                  </span>
                </button>
              );
            })}
        </div>
        {!membership.complete && (
          <span className="data-readout text-micro text-text-muted">
            MEMBERSHIP {membership.loadedPlaylists}/{membership.totalPlaylists}{" "}
            PL
          </span>
        )}
      </div>

      <FieldGuideCard
        mode="tracks"
        stats={{
          trackCount: trackMap.data.points.length,
          clusterCount: trackMap.data.cluster_count,
          ari: trackMap.data.ari,
        }}
        position="bottom-left"
      />
    </div>
  );
}
