"use client";

import { useMemo } from "react";
import { Readout } from "@/components/panels/right-dock";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useArtistGalaxy } from "@/hooks/api/use-artist-galaxy";
import { useGraph } from "@/hooks/api/use-graph";
import { acousticColor, GREY_NODE, oklchString } from "@/lib/color/acoustic";

interface ArtistCardPanelContentProps {
  artistId: string;
  /** Flip to the playlist graph with this playlist highlighted. */
  onShowInGraph: (playlistId: number) => void;
  /** Jump the card to another in-library artist (similar-artist rows). */
  onOpenArtist: (artistId: string) => void;
}

/**
 * The artist card for a node picked on the galaxy: identity + genre tags,
 * the artist's library tracks, the playlists they bridge (each cross-links
 * to the playlist graph), and similar artists with in-library markers.
 * Everything renders from the galaxy payload — no extra fetches.
 */
export function ArtistCardPanelContent({
  artistId,
  onShowInGraph,
  onOpenArtist,
}: ArtistCardPanelContentProps) {
  const galaxy = useArtistGalaxy();
  const graph = useGraph();

  const node = useMemo(
    () => galaxy.data?.nodes.find((n) => n.id === artistId) ?? null,
    [galaxy.data, artistId],
  );
  const inGalaxy = useMemo(
    () => new Set(galaxy.data?.nodes.map((n) => n.id) ?? []),
    [galaxy.data],
  );

  const playlists = useMemo(
    () =>
      (node?.playlist_ids ?? [])
        .map((id) => graph.data?.nodes.find((n) => n.id === id) ?? null)
        .filter((n) => n !== null),
    [node, graph.data],
  );

  if (!node) {
    return (
      <p className="text-sm text-text-secondary">
        This artist isn't on the current galaxy — the map may have refreshed or
        the scope changed. Close the card and pick a node again.
      </p>
    );
  }

  const swatch = oklchString(
    node.centroid ? acousticColor(node.centroid) : GREY_NODE,
  );
  const hiddenTracks = node.track_count - node.tracks.length;

  return (
    <>
      <div className="flex items-start gap-sm">
        <span
          className="mt-[6px] inline-block size-[12px] flex-none rounded-xs"
          style={{ background: swatch }}
        />
        <div className="min-w-0">
          <div className="font-bold text-lg text-text-primary leading-snug">
            {node.name}
          </div>
          {node.genres.length > 0 && (
            <div className="mt-2xs flex flex-wrap gap-2xs">
              {node.genres.map((genre) => (
                <Badge
                  key={genre}
                  variant="outline"
                  className="border-border-subtle text-micro text-text-secondary"
                >
                  {genre}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex gap-xl">
        <Readout label="Tracks" value={String(node.track_count)} />
        <Readout label="Playlists" value={String(node.playlist_count)} />
      </div>

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">In your library</span>
        <div className="flex flex-col">
          {node.tracks.map((track) => (
            <span
              key={track.id}
              className="truncate rounded-xs px-2xs py-2xs text-sm text-text-primary"
            >
              {track.name}
            </span>
          ))}
        </div>
        {hiddenTracks > 0 && (
          <span className="data-readout text-micro text-text-muted">
            +{hiddenTracks} MORE
          </span>
        )}
      </section>

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">Bridges playlists</span>
        {playlists.length === 0 ? (
          <span className="text-sm text-text-secondary">
            No playlist in the current scope holds this artist.
          </span>
        ) : (
          <div className="flex flex-col">
            {playlists.map((playlist) => (
              <div
                key={playlist.id}
                className="flex items-center gap-xs rounded-xs px-2xs py-2xs hover:bg-surface-2"
              >
                <span
                  className="inline-block size-[8px] flex-none rounded-xs"
                  style={{
                    background: oklchString(
                      playlist.centroid
                        ? acousticColor(playlist.centroid)
                        : GREY_NODE,
                    ),
                  }}
                />
                <span className="truncate text-sm text-text-primary">
                  {playlist.name}
                </span>
                <span className="data-readout text-micro text-text-muted">
                  {playlist.track_count}
                </span>
                <button
                  type="button"
                  onClick={() => onShowInGraph(playlist.id)}
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

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">Similar artists</span>
        {node.similar.length === 0 ? (
          <span className="text-sm text-text-secondary">
            No listener-similarity data for this artist yet — it arrives with
            enrichment.
          </span>
        ) : (
          <div className="flex flex-col">
            {node.similar.map((similar) => {
              const key = similar.name.toLowerCase();
              const jumpable = similar.in_library && inGalaxy.has(key);
              return (
                <div
                  key={similar.name}
                  className="flex items-center gap-xs rounded-xs px-2xs py-2xs hover:bg-surface-2"
                >
                  {jumpable ? (
                    <button
                      type="button"
                      onClick={() => onOpenArtist(key)}
                      className="cursor-pointer truncate text-sm text-text-primary hover:underline"
                      title="Open this artist's card"
                    >
                      {similar.name}
                    </button>
                  ) : (
                    <span className="truncate text-sm text-text-secondary">
                      {similar.name}
                    </span>
                  )}
                  <span className="data-readout text-micro text-text-muted">
                    {similar.weight.toFixed(2)}
                  </span>
                  {similar.in_library && (
                    <span className="data-readout ml-auto text-micro text-text-primary">
                      IN LIBRARY
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}
