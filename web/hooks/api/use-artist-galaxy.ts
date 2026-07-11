"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type ArtistGalaxyResponse,
  artistGalaxyResponseSchema,
} from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

/**
 * The artist galaxy: every credited artist across the in-scope playlists,
 * with co-playlist and similarity edges. Follows the same owned/followed
 * scope as the other maps; the payload is snapshot-cached server-side.
 */
export function useArtistGalaxy() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.galaxyScoped(ownedOnly),
    queryFn: async (): Promise<ArtistGalaxyResponse> =>
      artistGalaxyResponseSchema.parse(
        await request<unknown>("GET", "/v1/graph/artists", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
