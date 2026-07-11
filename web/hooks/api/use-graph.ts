"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import { type GraphResponse, graphResponseSchema } from "@/lib/api/schemas";
import { graphFixture } from "@/lib/fixtures/graph";
import { useUiStore } from "@/lib/store/ui";

/**
 * NEXT_PUBLIC_CRATE_GRAPH_FIXTURE=1 serves the demo payload instead of
 * GET /v1/graph/playlists. Once the analytics engine ships that endpoint,
 * drop the flag — nothing else changes; the zod parse below is the contract.
 */
const useFixture = process.env.NEXT_PUBLIC_CRATE_GRAPH_FIXTURE === "1";

async function fetchGraph(ownedOnly: boolean): Promise<GraphResponse | null> {
  if (useFixture) return graphResponseSchema.parse(graphFixture);
  try {
    const json = await request<unknown>("GET", "/v1/graph/playlists", {
      params: { owned_only: ownedOnly },
    });
    return graphResponseSchema.parse(json);
  } catch (error) {
    // 404 = the analytics engine hasn't computed a graph yet. Surfaced as a
    // designed "not yet computed" state, not an error.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/**
 * The map defaults to playlists the account owns; the "include followed"
 * chrome toggle widens it to everything the account follows.
 */
export function useGraph() {
  const includeFollowed = useUiStore((state) => state.includeFollowed);
  const ownedOnly = !includeFollowed;
  return useQuery({
    queryKey: queryKeys.graphScoped(ownedOnly),
    queryFn: () => fetchGraph(ownedOnly),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
