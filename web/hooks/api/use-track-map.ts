"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type TrackMapResponse,
  trackMapResponseSchema,
} from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

async function fetchTrackMap(
  ownedOnly: boolean,
): Promise<TrackMapResponse | null> {
  try {
    const json = await request<unknown>("GET", "/v1/map/tracks", {
      params: { owned_only: ownedOnly },
    });
    return trackMapResponseSchema.parse(json);
  } catch (error) {
    // 404 = the projection hasn't been computed for this library yet.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/**
 * The track field: every enriched track projected to 2D. Follows the same
 * owned/followed scope as the playlist graph. The first read for a scope can
 * be slow (UMAP computes lazily server-side), hence the long stale time.
 */
export function useTrackMap() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.trackMapScoped(ownedOnly),
    queryFn: () => fetchTrackMap(ownedOnly),
    staleTime: 5 * 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
