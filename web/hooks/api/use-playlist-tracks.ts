"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import { playlistTrackCollectionSchema } from "@/lib/api/schemas";

export const TRACK_PAGE_SIZE = 50;

export function usePlaylistTracks(playlistId: number | null, offset: number) {
  return useQuery({
    queryKey: queryKeys.playlistTracks(playlistId ?? -1, offset),
    enabled: playlistId !== null,
    placeholderData: keepPreviousData,
    queryFn: async () =>
      playlistTrackCollectionSchema.parse(
        await request<unknown>("GET", `/v1/playlists/${playlistId}/tracks`, {
          params: { limit: TRACK_PAGE_SIZE, offset },
        }),
      ),
  });
}
