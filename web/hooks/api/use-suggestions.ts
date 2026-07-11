"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type DiscoveryRunResult,
  discoveryRunResultSchema,
  type FeedbackResult,
  feedbackResultSchema,
  type SuggestionQueue,
  suggestionQueueSchema,
} from "@/lib/api/schemas";

/** The ranked suggestion queue for one playlist (the deck's data source). */
export function useSuggestions(playlistId: number | null) {
  return useQuery({
    queryKey: queryKeys.suggestions(playlistId ?? -1),
    enabled: playlistId !== null,
    queryFn: async (): Promise<SuggestionQueue> =>
      suggestionQueueSchema.parse(
        await request<unknown>(
          "GET",
          `/v1/playlists/${playlistId}/suggestions`,
        ),
      ),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

/**
 * Review decision on one suggestion. Accept routes through the journaled
 * write path server-side, so the result carries a journal id for the undo
 * toast; accept also reshapes the library, hence the broad invalidation.
 */
export function useSuggestionFeedback(playlistId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      candidateId: number;
      action: "accept" | "reject" | "skip";
    }): Promise<FeedbackResult> =>
      feedbackResultSchema.parse(
        await request<unknown>(
          "POST",
          `/v1/suggestions/${input.candidateId}/feedback`,
          { body: { action: input.action } },
        ),
      ),
    onSettled: (_result, _error, input) => {
      if (playlistId !== null) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.suggestions(playlistId),
        });
      }
      if (input.action === "accept") {
        queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
        queryClient.invalidateQueries({ queryKey: queryKeys.graph });
        queryClient.invalidateQueries({ queryKey: queryKeys.journal });
        queryClient.invalidateQueries({ queryKey: queryKeys.libraryStats });
      }
    },
  });
}

/** Kick a discovery pass (generation, resolution, previews) for a playlist. */
export function useDiscoveryRun(playlistId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<DiscoveryRunResult> =>
      discoveryRunResultSchema.parse(
        await request<unknown>("POST", "/v1/discovery/run", {
          body: { playlist_id: playlistId ?? undefined },
        }),
      ),
    onSettled: () => {
      if (playlistId !== null) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.suggestions(playlistId),
        });
      }
    },
  });
}
