"use client";

import { useMemo, useState } from "react";
import { FieldGuideCard } from "@/components/chrome/field-guide-card";
import { OklchLegend } from "@/components/explain/oklch-legend";
import ArtistGalaxyCanvas, {
  type GalaxyRenderNode,
} from "@/components/galaxy/artist-galaxy-canvas";
import { useArtistGalaxy } from "@/hooks/api/use-artist-galaxy";
import type { GalaxyNode, GraphResponse } from "@/lib/api/schemas";
import type { FlyTarget } from "@/lib/canvas/fly-to";
import {
  acousticColor,
  GREY_NODE,
  oklchString,
  selectionRing,
} from "@/lib/color/acoustic";
import { equalizedColor, rankEqualize } from "@/lib/color/equalize";
import { bridgingArtists, togglePin } from "@/lib/galaxy/logic";
import { useUiStore } from "@/lib/store/ui";

interface ArtistGalaxyProps {
  graph: GraphResponse;
  selectedArtistId: string | null;
  onSelectArtist: (artistId: string | null) => void;
  rightInset: number;
  reducedMotion: boolean;
  flyTo?: FlyTarget | null;
}

/**
 * The artist galaxy view: data wiring, states, and the bridge legend. Pin
 * one playlist to light its artists; pin a second to isolate the artists
 * bridging the pair — the connective tissue between two crates.
 */
export default function ArtistGalaxy({
  graph,
  selectedArtistId,
  onSelectArtist,
  rightInset,
  reducedMotion,
  flyTo = null,
}: ArtistGalaxyProps) {
  const galaxy = useArtistGalaxy();
  const selectedPlaylistId = useUiStore((s) => s.selectedPlaylistId);
  const [pins, setPins] = useState<number[]>([]);

  // G4 — equalize artist colours across the galaxy so they fill the gamut.
  const equalizer = useMemo(() => {
    const centroids = (galaxy.data?.nodes ?? [])
      .map((n) => n.centroid)
      .filter((c): c is NonNullable<typeof c> => c !== null);
    return centroids.length > 0 ? rankEqualize(centroids) : null;
  }, [galaxy.data]);

  const renderNodes = useMemo<GalaxyRenderNode[]>(() => {
    const nodes = galaxy.data?.nodes ?? [];
    return nodes.map((node) => {
      const color = node.centroid
        ? equalizer
          ? equalizedColor(node.centroid, equalizer)
          : acousticColor(node.centroid)
        : GREY_NODE;
      return {
        id: node.id,
        name: node.name,
        trackCount: node.track_count,
        fill: oklchString(color),
        ring: oklchString(selectionRing(color)),
        grey: node.centroid === null,
      };
    });
  }, [galaxy.data, equalizer]);

  // Full node data by id — the hover card reads photo/genres/similar from it.
  const nodeById = useMemo(() => {
    const m = new Map<string, GalaxyNode>();
    for (const n of galaxy.data?.nodes ?? []) m.set(n.id, n);
    return m;
  }, [galaxy.data]);

  // Pins drive the highlight; with none pinned, a playlist selected
  // elsewhere (palette, panel) lights its artists too.
  const highlightIds = useMemo(() => {
    const nodes = galaxy.data?.nodes ?? [];
    const effective =
      pins.length > 0
        ? pins
        : selectedPlaylistId !== null
          ? [selectedPlaylistId]
          : [];
    return bridgingArtists(nodes, effective);
  }, [galaxy.data, pins, selectedPlaylistId]);

  if (galaxy.isPending) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="micro-caps text-text-muted">CHARTING ARTISTS…</span>
      </div>
    );
  }

  if (galaxy.isError) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-xs">
        <span className="micro-caps text-danger">
          ARTIST GALAXY UNAVAILABLE
        </span>
        <button
          type="button"
          onClick={() => galaxy.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!galaxy.data || galaxy.data.nodes.length === 0) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-xs">
        <span className="micro-caps text-text-muted">GALAXY EMPTY</span>
        <p className="max-w-[46ch] text-center text-sm text-text-secondary">
          Artists appear here once synced playlists hold tracks. Run a sync,
          then come back.
        </p>
      </div>
    );
  }

  const coverage = galaxy.data.coverage;
  const bridgeMode = pins.length === 2;

  return (
    <div className="absolute inset-0">
      <ArtistGalaxyCanvas
        nodes={renderNodes}
        edges={galaxy.data.edges}
        nodeData={nodeById}
        highlightIds={highlightIds}
        selectedId={selectedArtistId}
        onSelect={onSelectArtist}
        rightInset={rightInset}
        reducedMotion={reducedMotion}
        flyTo={flyTo}
      />

      {/* Bridge legend — pin one playlist to light it, two to see bridges. */}
      <div className="pointer-events-auto absolute top-[56px] left-lg z-10 flex w-[220px] flex-col gap-2xs">
        <div className="flex items-baseline justify-between">
          <span className="micro-caps text-text-muted">
            {bridgeMode ? "BRIDGE" : "PLAYLISTS"}
          </span>
          {pins.length > 0 && (
            <button
              type="button"
              onClick={() => setPins([])}
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
              const pinned = pins.includes(node.id);
              return (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => setPins((prev) => togglePin(prev, node.id))}
                  className={`flex cursor-pointer items-center gap-xs rounded-xs px-2xs py-[3px] text-left ${
                    pinned ? "bg-surface-2" : "hover:bg-surface-1"
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
                      pinned ? "text-text-primary" : "text-text-secondary"
                    }`}
                  >
                    {node.name}
                  </span>
                  {pinned && (
                    <span className="data-readout ml-auto text-micro text-text-primary">
                      PIN
                    </span>
                  )}
                </button>
              );
            })}
        </div>
        <span className="data-readout text-micro text-text-muted">
          {bridgeMode
            ? `${highlightIds?.size ?? 0} BRIDGING ARTISTS`
            : "PIN TWO PLAYLISTS TO SEE BRIDGES"}
        </span>
        {coverage.artists_shown < coverage.artists_total && (
          <span className="data-readout text-micro text-text-muted">
            SHOWING {coverage.artists_shown}/{coverage.artists_total} ARTISTS
          </span>
        )}
      </div>

      <FieldGuideCard
        mode="artists"
        stats={{
          artistsShown: coverage.artists_shown,
          artistsTotal: coverage.artists_total,
          bridgeCount: bridgeMode
            ? (highlightIds?.size ?? undefined)
            : undefined,
        }}
        position="bottom-left"
      />
      <OklchLegend position="bottom-right" />
    </div>
  );
}
