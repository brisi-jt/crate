"use client";

import { useMemo } from "react";
import {
  type FingerprintBarRow,
  FingerprintBars,
} from "@/components/deck/fingerprint-bars";
import { Readout } from "@/components/panels/right-dock";
import { Separator } from "@/components/ui/separator";
import { useGraph } from "@/hooks/api/use-graph";
import { useMembershipIndex } from "@/hooks/api/use-membership";
import { useTrackMap } from "@/hooks/api/use-track-map";
import { acousticColor, GREY_NODE, oklchString } from "@/lib/color/acoustic";
import { meanCentroid, pointColor } from "@/lib/field/color";

interface TrackCardPanelContentProps {
  trackId: number;
  /** Flip to the playlist graph with this playlist highlighted. */
  onShowInGraph: (playlistId: number) => void;
}

/**
 * Compact track card for a point picked on the track field: identity,
 * cluster, owning playlists (each row cross-links to the playlist graph),
 * and the feature fingerprint once per-track features ship on the payload.
 */
export function TrackCardPanelContent({
  trackId,
  onShowInGraph,
}: TrackCardPanelContentProps) {
  const trackMap = useTrackMap();
  const graph = useGraph();

  const playlistIds = useMemo(
    () => graph.data?.nodes.map((n) => n.id) ?? [],
    [graph.data],
  );
  const membership = useMembershipIndex(playlistIds, true);

  const point = useMemo(
    () => trackMap.data?.points.find((p) => p.track_id === trackId) ?? null,
    [trackMap.data, trackId],
  );

  const owners = useMemo(() => {
    const ids = point?.playlist_ids ?? membership.byTrack.get(trackId) ?? [];
    return ids
      .map((id) => graph.data?.nodes.find((n) => n.id === id) ?? null)
      .filter((n) => n !== null);
  }, [point, membership.byTrack, trackId, graph.data]);

  const ownerCentroids = useMemo(() => owners.map((n) => n.centroid), [owners]);
  const color = pointColor(point?.features ?? null, ownerCentroids);
  const swatch = oklchString(color);
  const profile = meanCentroid(ownerCentroids);
  const profileSwatch = profile ? oklchString(acousticColor(profile)) : null;

  if (!point) {
    return (
      <p className="text-sm text-text-secondary">
        This track isn't on the current field — the projection may have
        refreshed. Close the card and pick a point again.
      </p>
    );
  }

  const features = point.features ?? null;
  const fingerprintRows: FingerprintBarRow[] | null = features
    ? [
        {
          key: "energy",
          label: "Energy",
          value: features.energy,
          tick: profile?.energy ?? null,
        },
        {
          key: "valence",
          label: "Valence",
          value: features.valence,
          tick: profile?.valence ?? null,
        },
        {
          key: "acousticness",
          label: "Acousticness",
          value: features.acousticness,
          tick: profile?.acousticness ?? null,
        },
      ]
    : null;

  return (
    <>
      <div className="flex items-start gap-sm">
        <span
          className="mt-[6px] inline-block size-[12px] flex-none rounded-xs"
          style={{ background: swatch }}
        />
        <div className="min-w-0">
          <div className="font-bold text-lg text-text-primary leading-snug">
            {point.name}
          </div>
          <div className="text-sm text-text-secondary">{point.artist}</div>
        </div>
      </div>

      <div className="flex gap-xl">
        <Readout
          label="Cluster"
          value={point.cluster < 0 ? "NOISE" : `C${point.cluster}`}
        />
        <Readout label="Playlists" value={String(owners.length)} />
      </div>

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">Fingerprint</span>
        {fingerprintRows ? (
          <FingerprintBars
            rows={fingerprintRows}
            valueColor={swatch}
            tickColor={profileSwatch}
          />
        ) : (
          <div className="flex flex-col gap-2xs rounded-md border border-border-subtle border-dashed px-md py-sm">
            <span className="text-sm text-text-secondary">
              Per-track percentiles aren't in the map payload yet — this track's
              color comes from the playlists that hold it.
            </span>
          </div>
        )}
      </section>

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">In playlists</span>
        {!membership.complete && owners.length === 0 ? (
          <span className="data-readout text-micro text-text-muted">
            MEMBERSHIP LOADING · {membership.loadedPlaylists}/
            {membership.totalPlaylists} PL
          </span>
        ) : owners.length === 0 ? (
          <span className="text-sm text-text-secondary">
            No playlist in the current scope holds this track.
          </span>
        ) : (
          <div className="flex flex-col">
            {owners.map((node) => (
              <div
                key={node.id}
                className="flex items-center gap-xs rounded-xs px-2xs py-2xs hover:bg-surface-2"
              >
                <span
                  className="inline-block size-[8px] flex-none rounded-xs"
                  style={{
                    background: oklchString(
                      node.centroid ? acousticColor(node.centroid) : GREY_NODE,
                    ),
                  }}
                />
                <span className="truncate text-sm text-text-primary">
                  {node.name}
                </span>
                <span className="data-readout text-micro text-text-muted">
                  {node.track_count}
                </span>
                <button
                  type="button"
                  onClick={() => onShowInGraph(node.id)}
                  className="micro-caps ml-auto cursor-pointer text-text-muted hover:text-text-primary"
                  title="Flip to the playlist graph with this playlist highlighted"
                >
                  SHOW IN GRAPH
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
