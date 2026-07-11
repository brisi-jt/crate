"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import { playlistCollectionSchema } from "@/lib/api/schemas";

export function usePlaylists() {
  return useQuery({
    queryKey: queryKeys.playlists,
    queryFn: async () =>
      playlistCollectionSchema.parse(
        await request<unknown>("GET", "/v1/playlists", {
          params: { limit: 100, offset: 0 },
        }),
      ),
  });
}
