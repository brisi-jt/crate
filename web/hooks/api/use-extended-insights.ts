"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type ExtendedInsights,
  extendedInsightsSchema,
  type PinCandidates,
  pinCandidatesSchema,
} from "@/lib/api/schemas-extended";
import { useUiStore } from "@/lib/store/ui";

/** Give up fast on 4xx; retry twice on 5xx/network. */
function extendedRetry(failureCount: number, error: unknown): boolean {
  return !(error instanceof ApiError && error.status < 500) && failureCount < 2;
}

/**
 * The extended survey — 24 insights mined from the seven deep tables
 * (play_events, saved_tracks, suggestion_feedback, discovery candidates,
 * top-items snapshots, radio, journal, calibration). Cached server-side and
 * scoped to the same owned/followed toggle as the base survey.
 */
export function useExtendedInsights() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.insightsExtendedScoped(ownedOnly),
    queryFn: async (): Promise<ExtendedInsights> =>
      extendedInsightsSchema.parse(
        await request<unknown>("GET", "/v1/insights/extended", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: extendedRetry,
  });
}

/**
 * The wide, family-tagged pin candidate pool for a surface. The client samples
 * a small, rotating subset of this (see lib/pins/sampler.ts) — fetching the
 * whole pool locally keeps the rotation seed off the server cache key.
 */
export function usePinCandidates(surface: "insights") {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.pinCandidates(surface, ownedOnly),
    queryFn: async (): Promise<PinCandidates> =>
      pinCandidatesSchema.parse(
        await request<unknown>("GET", "/v1/insights/pins/candidates", {
          params: { surface, owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: extendedRetry,
  });
}
