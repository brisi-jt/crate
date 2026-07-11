"use client";

import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import { type GraphResponse, graphResponseSchema } from "@/lib/api/schemas";
import { graphFixture } from "@/lib/fixtures/graph";

/**
 * NEXT_PUBLIC_CRATE_GRAPH_FIXTURE=1 serves the demo payload instead of
 * GET /v1/graph/playlists. Once the analytics engine ships that endpoint,
 * drop the flag — nothing else changes; the zod parse below is the contract.
 */
const useFixture = process.env.NEXT_PUBLIC_CRATE_GRAPH_FIXTURE === "1";

async function fetchGraph(): Promise<GraphResponse | null> {
  if (useFixture) return graphResponseSchema.parse(graphFixture);
  try {
    const json = await request<unknown>("GET", "/v1/graph/playlists");
    return graphResponseSchema.parse(json);
  } catch (error) {
    // 404 = the analytics engine hasn't computed a graph yet. Surfaced as a
    // designed "not yet computed" state, not an error.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function useGraph() {
  return useQuery({
    queryKey: queryKeys.graph,
    queryFn: fetchGraph,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}
