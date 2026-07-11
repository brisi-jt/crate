"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type PlaylistAnalytics,
  playlistAnalyticsSchema,
} from "@/lib/api/schemas";

/**
 * Per-playlist analytics: cohesion, outliers, overlaps, fingerprint, flow.
 * The endpoint is the analytics engine's to build — until it exists (404),
 * `data` resolves to null and the panel renders its "not yet computed"
 * readouts instead of an error.
 */
async function fetchAnalytics(
  playlistId: number,
): Promise<PlaylistAnalytics | null> {
  try {
    const json = await request<unknown>(
      "GET",
      `/v1/playlists/${playlistId}/analytics`,
    );
    return playlistAnalyticsSchema.parse(json);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function usePlaylistAnalytics(playlistId: number | null) {
  return useQuery({
    queryKey: queryKeys.playlistAnalytics(playlistId ?? -1),
    enabled: playlistId !== null,
    queryFn: () => fetchAnalytics(playlistId as number),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
