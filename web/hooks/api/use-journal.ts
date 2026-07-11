"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import { journalCollectionSchema, undoResultSchema } from "@/lib/api/schemas";

export function useJournal() {
  return useQuery({
    queryKey: queryKeys.journal,
    queryFn: async () =>
      journalCollectionSchema.parse(
        await request<unknown>("GET", "/v1/journal", {
          params: { limit: 50, offset: 0 },
        }),
      ),
  });
}

/**
 * Revert a journal entry. Any undo can move membership, order, names, and
 * even playlist existence — refresh everything derived from library state.
 */
export function useUndoJournal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (journalId: number) =>
      undoResultSchema.parse(
        await request<unknown>("POST", `/v1/journal/${journalId}/undo`),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.journal });
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
      queryClient.invalidateQueries({ queryKey: queryKeys.graph });
      queryClient.invalidateQueries({ queryKey: queryKeys.libraryStats });
    },
  });
}
