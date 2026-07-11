"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import { syncResultSchema, syncStatusSchema } from "@/lib/api/schemas";

export function useSyncStatus() {
  return useQuery({
    queryKey: queryKeys.syncStatus,
    queryFn: async () =>
      syncStatusSchema.parse(await request<unknown>("GET", "/v1/sync/status")),
    refetchInterval: 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

/**
 * Manual sync trigger. The API runs the pass inline, so a resolved mutation
 * means the pass finished — refresh everything derived from library state.
 */
export function useTriggerSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      syncResultSchema.parse(await request<unknown>("POST", "/v1/sync")),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.syncStatus });
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
      queryClient.invalidateQueries({ queryKey: queryKeys.graph });
    },
  });
}
