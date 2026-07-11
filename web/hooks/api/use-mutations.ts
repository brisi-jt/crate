"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import {
  type MutationResult,
  mutationResultSchema,
  type PlaylistTrackCollection,
} from "@/lib/api/schemas";

function useInvalidateLibrary() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
    queryClient.invalidateQueries({ queryKey: queryKeys.graph });
    queryClient.invalidateQueries({ queryKey: queryKeys.journal });
    queryClient.invalidateQueries({ queryKey: queryKeys.libraryStats });
  };
}

/** Instant single-track add (tier 1): journaled server-side, undo via toast. */
export function useAddTracks() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: async (input: {
      playlistId: number;
      trackIds: number[];
      position?: number;
    }): Promise<MutationResult> =>
      mutationResultSchema.parse(
        await request<unknown>(
          "POST",
          `/v1/playlists/${input.playlistId}/tracks`,
          {
            body: { track_ids: input.trackIds, position: input.position },
          },
        ),
      ),
    onSettled: invalidate,
  });
}

/**
 * Instant single-row remove (tier 1) with an optimistic page update: the row
 * disappears immediately; a failure rolls the page back; settle refetches.
 */
export function useRemoveTrackAt(playlistId: number) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: async (input: {
      position: number;
      /** Page offset of the row — locates the cached page to patch. */
      offset: number;
    }): Promise<MutationResult> =>
      mutationResultSchema.parse(
        await request<unknown>("DELETE", `/v1/playlists/${playlistId}/tracks`, {
          body: { positions: [input.position] },
        }),
      ),
    onMutate: async (input) => {
      const key = queryKeys.playlistTracks(playlistId, input.offset);
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<PlaylistTrackCollection>(key);
      if (previous) {
        queryClient.setQueryData<PlaylistTrackCollection>(key, {
          ...previous,
          total: previous.total - 1,
          items: previous.items.filter(
            (item) => item.position !== input.position,
          ),
        });
      }
      return { key, previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) {
        queryClient.setQueryData(context.key, context.previous);
      }
    },
    onSettled: invalidate,
  });
}

export function useRenamePlaylist() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: async (input: {
      playlistId: number;
      name?: string;
      description?: string;
    }): Promise<MutationResult> =>
      mutationResultSchema.parse(
        await request<unknown>("PATCH", `/v1/playlists/${input.playlistId}`, {
          body: { name: input.name, description: input.description },
        }),
      ),
    onSettled: invalidate,
  });
}

/** Apply a flow-suggested (or hand-built) full reorder. */
export function useReorderPlaylist() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: async (input: {
      playlistId: number;
      order: number[];
    }): Promise<MutationResult> =>
      mutationResultSchema.parse(
        await request<unknown>(
          "PUT",
          `/v1/playlists/${input.playlistId}/order`,
          {
            body: { order: input.order },
          },
        ),
      ),
    onSettled: invalidate,
  });
}
