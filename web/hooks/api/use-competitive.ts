"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type FlowApplyResult,
  type FlowArc,
  type FlowMood,
  flowApplyResultSchema,
  flowArcSchema,
  type ListeningDashboard,
  type ListeningRange,
  listeningDashboardSchema,
  type Obscurity,
  obscuritySchema,
  type QualityPlaylists,
  qualityPlaylistsSchema,
  type TasteDrift,
  tasteDriftSchema,
} from "@/lib/api/schemas-competitive";
import { useUiStore } from "@/lib/store/ui";

/** Give up fast on 4xx; retry twice on 5xx/network. */
function competitiveRetry(failureCount: number, error: unknown): boolean {
  return !(error instanceof ApiError && error.status < 500) && failureCount < 2;
}

/** F1 — listening-rhythm dashboard for a range. */
export function useListeningDashboard(range: ListeningRange) {
  return useQuery({
    queryKey: queryKeys.listeningDashboard(range),
    queryFn: async (): Promise<ListeningDashboard> =>
      listeningDashboardSchema.parse(
        await request<unknown>("GET", "/v1/listening/dashboard", {
          params: { range },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: competitiveRetry,
  });
}

/** F3 — library + per-playlist obscurity. */
export function useObscurity() {
  const includeFollowed = useUiStore((s) => s.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.obscurity(ownedOnly),
    queryFn: async (): Promise<Obscurity> =>
      obscuritySchema.parse(
        await request<unknown>("GET", "/v1/obscurity", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: competitiveRetry,
  });
}

/** F5 — taste drift; pass a snapshot id to compute the comparison. */
export function useTasteDrift(snapshotId: number | null) {
  const includeFollowed = useUiStore((s) => s.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.tasteDrift(snapshotId, ownedOnly),
    queryFn: async (): Promise<TasteDrift> =>
      tasteDriftSchema.parse(
        await request<unknown>("GET", "/v1/taste/drift", {
          params: {
            owned_only: ownedOnly,
            snapshot_id: snapshotId ?? undefined,
          },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: competitiveRetry,
  });
}

/** F6 — per-playlist quality breakdown. */
export function useQualityPlaylists() {
  const includeFollowed = useUiStore((s) => s.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.qualityPlaylists(ownedOnly),
    queryFn: async (): Promise<QualityPlaylists> =>
      qualityPlaylistsSchema.parse(
        await request<unknown>("GET", "/v1/quality/playlists", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: competitiveRetry,
  });
}

/**
 * F4 — flow-arc preview for one playlist + mood. Read-only: it never writes.
 * `enabled` gates the fetch so the tab only previews when it's open and a mood
 * is chosen.
 */
export function useFlowArc(
  playlistId: number,
  mood: FlowMood,
  enabled: boolean,
) {
  const includeFollowed = useUiStore((s) => s.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.flowArc(playlistId, mood),
    queryFn: async (): Promise<FlowArc> =>
      flowArcSchema.parse(
        await request<unknown>("GET", `/v1/playlists/${playlistId}/flow/arc`, {
          params: { mood, owned_only: ownedOnly },
        }),
      ),
    enabled,
    staleTime: 60_000,
    retry: competitiveRetry,
  });
}

/**
 * F4 apply — the one write. Journaled reorder; invalidates the library derived
 * caches (order changes touch analytics, graph, journal). Undo rides the
 * returned journal link, same as every other write.
 */
export function useApplyFlowArc(playlistId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (order: number[]): Promise<FlowApplyResult> =>
      flowApplyResultSchema.parse(
        await request<unknown>(
          "POST",
          `/v1/playlists/${playlistId}/flow/arc/apply`,
          { body: { order } },
        ),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
      queryClient.invalidateQueries({ queryKey: queryKeys.graph });
      queryClient.invalidateQueries({ queryKey: queryKeys.journal });
      queryClient.invalidateQueries({
        queryKey: queryKeys.playlistAnalytics(playlistId),
      });
      queryClient.invalidateQueries({ queryKey: ["quality-playlists"] });
      queryClient.invalidateQueries({ queryKey: ["flow-arc", playlistId] });
    },
  });
}
