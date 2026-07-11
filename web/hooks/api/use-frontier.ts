"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type DiscoveryRunResult,
  discoveryRunResultSchema,
  type FrontierResponse,
  frontierResponseSchema,
} from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

/**
 * The genre frontier: where the library lives in genre space and which
 * genres border it. Same owned/followed scope as the maps.
 */
export function useFrontier() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.frontierScoped(ownedOnly),
    queryFn: async (): Promise<FrontierResponse> =>
      frontierResponseSchema.parse(
        await request<unknown>("GET", "/v1/discovery/frontier", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

/**
 * Genre-seeded discovery pass: candidates come from the frontier genre's
 * exemplar artists, targeted at one playlist. The target's suggestion queue
 * refreshes when the pass lands, so the deck picks the new candidates up.
 */
export function useSeedDiscovery() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      playlistId: number;
      genre: string;
    }): Promise<DiscoveryRunResult> =>
      discoveryRunResultSchema.parse(
        await request<unknown>("POST", "/v1/discovery/run", {
          body: { playlist_id: input.playlistId, genre_seed: input.genre },
        }),
      ),
    onSettled: (_result, _error, input) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.suggestions(input.playlistId),
      });
    },
  });
}
