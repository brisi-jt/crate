"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type Edition,
  type EditionCollection,
  editionCollectionSchema,
  editionSchema,
  type InsightPins,
  type Insights,
  insightPinsSchema,
  insightsSchema,
} from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

/** Retry policy shared across insight reads: give up fast on 4xx. */
function insightRetry(failureCount: number, error: unknown): boolean {
  return !(error instanceof ApiError && error.status < 500) && failureCount < 2;
}

/**
 * The survey — one section-shaped reading of the whole library. Scoped to the
 * same owned/followed toggle as the maps, cached server-side under the
 * insights snapshot kind and auto-invalidated by sync/enrichment.
 */
export function useInsights() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.insightsScoped(ownedOnly),
    queryFn: async (): Promise<Insights> =>
      insightsSchema.parse(
        await request<unknown>("GET", "/v1/insights", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: insightRetry,
  });
}

/** The field journal: the list of frozen weekly editions, newest first. */
export function useEditions() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.editionsScoped(ownedOnly),
    queryFn: async (): Promise<EditionCollection> =>
      editionCollectionSchema.parse(
        await request<unknown>("GET", "/v1/insights/editions", {
          params: { owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: insightRetry,
  });
}

/** One frozen edition with its full narrative. */
export function useEdition(editionId: number | null) {
  return useQuery({
    queryKey:
      editionId !== null ? queryKeys.edition(editionId) : ["editions", "none"],
    queryFn: async (): Promise<Edition> =>
      editionSchema.parse(
        await request<unknown>("GET", `/v1/insights/editions/${editionId}`),
      ),
    enabled: editionId !== null,
    staleTime: 5 * 60_000,
    retry: insightRetry,
  });
}

/**
 * Compile (or rebuild) this week's edition, then refresh the edition list so
 * the band picks up the new reading. Weekly editions also compile on the
 * scheduler; this is the on-demand COMPILE NOW action.
 */
export function useCompileEdition() {
  const queryClient = useQueryClient();
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useMutation({
    mutationFn: async (): Promise<Edition> =>
      editionSchema.parse(
        await request<unknown>("POST", "/v1/insights/editions/compile", {
          params: { owned_only: ownedOnly },
        }),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.editions });
    },
  });
}

/**
 * Insight pins for one canvas surface — the annotated-atlas layer. Deterministic
 * and cheap (recomputed from the cached survey each request), scoped to the same
 * owned/followed toggle. `graph|field|galaxy` are the API surface names.
 */
export function useInsightPins(surface: "graph" | "field" | "galaxy") {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.insightPins(surface, ownedOnly),
    queryFn: async (): Promise<InsightPins> =>
      insightPinsSchema.parse(
        await request<unknown>("GET", "/v1/insights/pins", {
          params: { surface, owned_only: ownedOnly },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: insightRetry,
  });
}
