"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type Playlist,
  playlistCollectionSchema,
  type QueueCollection,
  queueCollectionSchema,
  type TriageApplyResult,
  type TriageCleanupResult,
  type TriageIntelligence,
  type TriageSetting,
  triageApplyResultSchema,
  triageCleanupResultSchema,
  triageIntelligenceSchema,
  triageSettingSchema,
} from "@/lib/api/schemas";
import { queueParams } from "@/lib/triage/queue-params";
import type { ApplyBody } from "@/lib/triage/selection";

// ------------------------------------------------------- owned playlists

const PLAYLIST_PAGE = 100;
const MAX_PLAYLIST_PAGES = 20; // 2k playlists — far beyond any real library

/**
 * Every live owned playlist, walked across pages (the list endpoint caps the
 * page size). Feeds the source picker and the destination list, so the picker
 * can search the full owned set — not just the first page.
 */
export function useOwnedPlaylists() {
  return useQuery({
    queryKey: ["triage", "owned-playlists"],
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<Playlist[]> => {
      const owned: Playlist[] = [];
      for (let page = 0; page < MAX_PLAYLIST_PAGES; page++) {
        const collection = playlistCollectionSchema.parse(
          await request<unknown>("GET", "/v1/playlists", {
            params: { limit: PLAYLIST_PAGE, offset: page * PLAYLIST_PAGE },
          }),
        );
        for (const pl of collection.items) {
          if (pl.is_owned && !pl.is_deleted) owned.push(pl);
        }
        if ((page + 1) * PLAYLIST_PAGE >= collection.total) break;
      }
      return owned;
    },
  });
}

// ------------------------------------------------------------------- setting

/** The account's current triage source (liked ⇄ a designated owned playlist). */
export function useTriageSetting() {
  return useQuery({
    queryKey: queryKeys.triageSetting,
    queryFn: async (): Promise<TriageSetting> =>
      triageSettingSchema.parse(await request<unknown>("GET", "/v1/me/triage")),
    staleTime: 60_000,
  });
}

export type TriageSourceUpdate =
  | { source: "liked" }
  | { source: "playlist"; playlistId: number };

/**
 * Switch the triage source. The body is explicit — `{source:"liked"}` clears,
 * `{source:"playlist", playlist_id:N}` sets — so returning to Liked Songs is
 * always reachable (an omitted field would be indistinguishable from null).
 */
export function useSetTriageSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (update: TriageSourceUpdate): Promise<TriageSetting> => {
      const body =
        update.source === "liked"
          ? { source: "liked" }
          : { source: "playlist", playlist_id: update.playlistId };
      return triageSettingSchema.parse(
        await request<unknown>("PUT", "/v1/me/triage", { body }),
      );
    },
    onSuccess: (setting) => {
      queryClient.setQueryData(queryKeys.triageSetting, setting);
      // The queue is source-scoped — drop every cached page on a switch.
      queryClient.invalidateQueries({ queryKey: ["triage", "queue"] });
    },
  });
}

// --------------------------------------------------------------------- queue

/**
 * One page of the triage queue. `keepPreviousData` holds the strip steady
 * while a new page (or a slider change) loads instead of flashing empty.
 */
export function useTriageQueue(input: {
  source: "liked" | "playlist";
  maxPlaylists: number;
  offset: number;
  enabled?: boolean;
}) {
  const params = queueParams({
    source: input.source,
    maxPlaylists: input.maxPlaylists,
    offset: input.offset,
  });
  return useQuery({
    queryKey: [
      ...queryKeys.triageQueue(input.source, input.maxPlaylists),
      input.offset,
    ],
    enabled: input.enabled ?? true,
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<QueueCollection> =>
      queueCollectionSchema.parse(
        await request<unknown>("GET", "/v1/triage/queue", {
          params: { ...params },
        }),
      ),
  });
}

// -------------------------------------------------------------- intelligence

/**
 * Per-track filing intelligence. When `new_category.status` is `pending` the
 * read schedules a background cluster compute, so the query refetches on an
 * interval until it resolves to `ready`/`empty`.
 */
export function useTriageIntelligence(input: {
  trackId: number | null;
  maxPlaylists: number;
}) {
  return useQuery({
    queryKey:
      input.trackId === null
        ? ["triage", "intelligence", "none"]
        : queryKeys.triageIntelligence(input.trackId, input.maxPlaylists),
    enabled: input.trackId !== null,
    queryFn: async (): Promise<TriageIntelligence> =>
      triageIntelligenceSchema.parse(
        await request<unknown>(
          "GET",
          `/v1/triage/tracks/${input.trackId}/intelligence`,
          { params: { max_playlists: input.maxPlaylists } },
        ),
      ),
    // Poll only while the new-category clusterer is still working.
    refetchInterval: (query) =>
      query.state.data?.new_category.status === "pending" ? 2500 : false,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

// -------------------------------------------------- apply + cleanup (writes)

/**
 * Widen the library-mutation invalidation for a triage filing. The existing
 * `useInvalidateLibrary` cascade (playlists/graph/journal/libraryStats) misses
 * two caches triage touches: per-playlist `suggestions` (a new member shifts
 * the ranker) and the net-new `saved` roster (an unsave removes a like).
 */
function useInvalidateAfterFiling() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
    queryClient.invalidateQueries({ queryKey: queryKeys.graph });
    queryClient.invalidateQueries({ queryKey: queryKeys.journal });
    queryClient.invalidateQueries({ queryKey: queryKeys.libraryStats });
    // suggestions: keyed per playlist under the `playlists` prefix already —
    // invalidate the bare prefix so every playlist's suggestion queue refreshes.
    queryClient.invalidateQueries({ queryKey: ["playlists"] });
    queryClient.invalidateQueries({ queryKey: queryKeys.saved });
    queryClient.invalidateQueries({ queryKey: ["triage"] });
  };
}

/** File one track into destinations / a new playlist in one journaled action. */
export function useTriageApply() {
  const invalidate = useInvalidateAfterFiling();
  return useMutation({
    mutationFn: async (body: ApplyBody): Promise<TriageApplyResult> =>
      triageApplyResultSchema.parse(
        await request<unknown>("POST", "/v1/triage/apply", { body }),
      ),
    onSettled: invalidate,
  });
}

export interface CleanupInput {
  source: "liked" | "playlist";
  playlist_id?: number;
  track_ids: number[];
}

/** Remove filed songs from the source (unsave in liked mode). Journaled. */
export function useTriageCleanup() {
  const invalidate = useInvalidateAfterFiling();
  return useMutation({
    mutationFn: async (body: CleanupInput): Promise<TriageCleanupResult> =>
      triageCleanupResultSchema.parse(
        await request<unknown>("POST", "/v1/triage/cleanup", { body }),
      ),
    onSettled: invalidate,
  });
}
