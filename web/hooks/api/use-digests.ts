"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/keys";
import {
  type Digest,
  type DigestCollection,
  digestCollectionSchema,
  digestSchema,
} from "@/lib/api/schemas";

/** The inbox reading list: weekly digests, newest first. */
export function useDigests() {
  return useQuery({
    queryKey: queryKeys.digests,
    queryFn: async (): Promise<DigestCollection> =>
      digestCollectionSchema.parse(
        await request<unknown>("GET", "/v1/digests", {
          params: { limit: 20, offset: 0 },
        }),
      ),
    staleTime: 5 * 60_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status < 500) && failureCount < 2,
  });
}

/** One digest with its items in reading order. */
export function useDigest(digestId: number | null) {
  return useQuery({
    queryKey: queryKeys.digest(digestId ?? -1),
    enabled: digestId !== null,
    queryFn: async (): Promise<Digest> =>
      digestSchema.parse(
        await request<unknown>("GET", `/v1/digests/${digestId}`),
      ),
  });
}

/**
 * Build (or rebuild) the current week's digest on demand. Regeneration
 * resets read_at, so the refreshed digest reads as unread again.
 */
export function useGenerateDigest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<Digest> =>
      digestSchema.parse(
        await request<unknown>("POST", "/v1/digest/generate", { body: {} }),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.digests });
    },
  });
}

/** Stamp a digest read — clears the chrome's unread marker. */
export function useMarkDigestRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (digestId: number): Promise<Digest> =>
      digestSchema.parse(
        await request<unknown>("POST", `/v1/digests/${digestId}/read`),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.digests });
    },
  });
}
