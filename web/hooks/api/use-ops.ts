"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/keys";
import {
  type ApplyResult,
  applyResultSchema,
  type OpPreview,
  opPreviewSchema,
} from "@/lib/api/schemas";

export interface PreviewInput {
  operation: string;
  sourceIds: number[];
  targetId?: number | null;
  newPlaylistName?: string | null;
}

/** Dry run: computes and stores the exact delta apply would perform. */
export function useOpsPreview() {
  return useMutation({
    mutationFn: async (input: PreviewInput): Promise<OpPreview> =>
      opPreviewSchema.parse(
        await request<unknown>("POST", "/v1/ops/preview", {
          body: {
            operation: input.operation,
            source_ids: input.sourceIds,
            target_id: input.targetId ?? null,
            new_playlist_name: input.newPlaylistName ?? null,
          },
        }),
      ),
  });
}

/**
 * Replay a stored preview. A 409 PREVIEW_STALE means the library moved since
 * the preview — the panel surfaces it as a re-preview prompt, not an error.
 */
export function useOpsApply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (previewId: number): Promise<ApplyResult> =>
      applyResultSchema.parse(
        await request<unknown>("POST", "/v1/ops/apply", {
          body: { preview_id: previewId },
        }),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.playlists });
      queryClient.invalidateQueries({ queryKey: queryKeys.graph });
      queryClient.invalidateQueries({ queryKey: queryKeys.journal });
      queryClient.invalidateQueries({ queryKey: queryKeys.libraryStats });
    },
  });
}
