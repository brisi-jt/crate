"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import { type LibraryStats, libraryStatsSchema } from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

/**
 * Library-wide analytics: temporal drift, duplicates, clusters-vs-playlists.
 * Same pending contract as playlist analytics: a 404 means "not yet
 * computed" and resolves to null rather than erroring.
 */
async function fetchLibraryStats(
  ownedOnly: boolean,
): Promise<LibraryStats | null> {
  try {
    const json = await request<unknown>("GET", "/v1/analytics/library", {
      params: { owned_only: ownedOnly },
    });
    return libraryStatsSchema.parse(json);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Stats follow the map's scope: owned playlists unless followed are shown. */
export function useLibraryStats(enabled: boolean) {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.libraryStatsScoped(ownedOnly),
    enabled,
    queryFn: () => fetchLibraryStats(ownedOnly),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
