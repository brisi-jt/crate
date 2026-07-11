"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import { type LibraryStats, libraryStatsSchema } from "@/lib/api/schemas";

/**
 * Library-wide analytics: temporal drift, duplicates, clusters-vs-playlists.
 * Same pending contract as playlist analytics: a 404 means "not yet
 * computed" and resolves to null rather than erroring.
 */
async function fetchLibraryStats(): Promise<LibraryStats | null> {
  try {
    const json = await request<unknown>("GET", "/v1/analytics/library");
    return libraryStatsSchema.parse(json);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function useLibraryStats(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.libraryStats,
    enabled,
    queryFn: fetchLibraryStats,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
