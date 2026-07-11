"use client";

import { useQueries } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import { playlistTrackCollectionSchema } from "@/lib/api/schemas";

const PAGE_SIZE = 100;
const MAX_PAGES = 60; // 6k tracks per playlist — far beyond any real playlist

/** Track↔playlist membership within the current map scope. */
export interface MembershipIndex {
  byTrack: Map<number, number[]>;
  byPlaylist: Map<number, number[]>;
  loadedPlaylists: number;
  totalPlaylists: number;
  complete: boolean;
}

async function fetchTrackIds(playlistId: number): Promise<number[]> {
  const ids: number[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const collection = playlistTrackCollectionSchema.parse(
      await request<unknown>("GET", `/v1/playlists/${playlistId}/tracks`, {
        params: { limit: PAGE_SIZE, offset: page * PAGE_SIZE },
      }),
    );
    for (const item of collection.items) ids.push(item.track.id);
    if ((page + 1) * PAGE_SIZE >= collection.total) break;
  }
  return ids;
}

/**
 * Client-side membership join for the track field: the map payload carries no
 * playlist ids per point, so the rosters come from the per-playlist track
 * listings, cached and loaded progressively — points tint in as pages land.
 */
export function useMembershipIndex(
  playlistIds: number[],
  enabled: boolean,
): MembershipIndex {
  return useQueries({
    queries: playlistIds.map((playlistId) => ({
      queryKey: queryKeys.playlistTrackIds(playlistId),
      queryFn: () => fetchTrackIds(playlistId),
      enabled,
      staleTime: 5 * 60_000,
    })),
    // combine keeps the returned index referentially stable between renders
    // unless an underlying roster actually changed.
    combine: (results) => {
      const byTrack = new Map<number, number[]>();
      const byPlaylist = new Map<number, number[]>();
      let loaded = 0;
      results.forEach((result, index) => {
        if (!result.data) return;
        loaded += 1;
        const playlistId = playlistIds[index];
        byPlaylist.set(playlistId, result.data);
        for (const trackId of result.data) {
          const owners = byTrack.get(trackId);
          if (owners) owners.push(playlistId);
          else byTrack.set(trackId, [playlistId]);
        }
      });
      return {
        byTrack,
        byPlaylist,
        loadedPlaylists: loaded,
        totalPlaylists: playlistIds.length,
        complete: loaded === playlistIds.length,
      };
    },
  });
}
