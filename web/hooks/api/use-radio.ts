"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import {
  type RadioItem,
  type RadioSession,
  radioItemSchema,
  radioSessionSchema,
} from "@/lib/api/schemas";

export type RadioSeed =
  | { playlistId: number }
  | { genre: string }
  | { trackIds: number[] };

/** Start a radio session from one seed (playlist, genre, or tracks). */
export function useCreateRadio() {
  return useMutation({
    mutationFn: async (seed: RadioSeed): Promise<RadioSession> => {
      const body =
        "playlistId" in seed
          ? { playlist_id: seed.playlistId }
          : "genre" in seed
            ? { genre_seed: seed.genre }
            : { track_ids: seed.trackIds };
      return radioSessionSchema.parse(
        await request<unknown>("POST", "/v1/radio", { body }),
      );
    },
  });
}

/** Reload a persisted radio session (items, verdicts, progress). */
export function useRadio(radioId: number | null) {
  return useQuery({
    queryKey: queryKeys.radio(radioId ?? -1),
    enabled: radioId !== null,
    queryFn: async (): Promise<RadioSession> =>
      radioSessionSchema.parse(
        await request<unknown>("GET", `/v1/radio/${radioId}`),
      ),
  });
}

/**
 * Record a verdict on one radio item. Keep with addToPlaylistId routes a
 * candidate through the journaled add path — the result carries the journal
 * id for the undo toast, and library-derived caches refresh.
 */
export function useRadioItemFeedback(radioId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      itemId: number;
      action: "keep" | "skip";
      addToPlaylistId?: number;
    }): Promise<RadioItem> =>
      radioItemSchema.parse(
        await request<unknown>(
          "POST",
          `/v1/radio/${radioId}/items/${input.itemId}/feedback`,
          {
            body: {
              action: input.action,
              add_to_playlist_id: input.addToPlaylistId ?? null,
            },
          },
        ),
      ),
    onSettled: (result) => {
      if (radioId !== null) {
        queryClient.invalidateQueries({ queryKey: queryKeys.radio(radioId) });
      }
      if (result?.candidate_id != null) {
        // Verdicts on candidates re-weight every suggestion queue (the
        // playlists prefix covers the per-playlist suggestion caches).
        queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
      }
      if (result?.journal_id != null) {
        queryClient.invalidateQueries({ queryKey: queryKeys.graph });
        queryClient.invalidateQueries({ queryKey: queryKeys.journal });
        queryClient.invalidateQueries({ queryKey: queryKeys.libraryStats });
      }
    },
  });
}
