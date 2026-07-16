import { z } from "zod";
import { request } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

/**
 * Result of POST /v1/previews/refresh.
 * The API re-searches Deezer and returns a fresh URL (candidate/radio item)
 * or a fresh-for-now URL (track_id path — not persisted to the catalog).
 */
const previewRefreshResultSchema = z.object({
  preview_url: z.string().nullable(),
  expires_hint_seconds: z.number(),
});

export type PreviewTarget =
  | { candidate_id: number }
  | { radio_item_id: number }
  | { track_id: number };

/**
 * One-retry helper: on a 403 playing a stored preview URL, call this once to
 * get a fresh URL.
 *
 * Returns the fresh URL string on success, or null on PREVIEW_UNRESOLVABLE
 * (caller should stop retrying and show the no-preview / open-in-Spotify
 * treatment). Re-throws on network errors or unexpected server failures so
 * the caller can decide whether to toast.
 *
 * Never called more than once per play attempt — callers must enforce this.
 */
export async function refreshPreviewUrl(
  target: PreviewTarget,
): Promise<string | null> {
  try {
    const result = previewRefreshResultSchema.parse(
      await request<unknown>("POST", "/v1/previews/refresh", { body: target }),
    );
    return result.preview_url;
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.problem?.error_code === "PREVIEW_UNRESOLVABLE" ||
        error.status === 404)
    ) {
      // No preview available for this entity — caller shows no-preview UI.
      return null;
    }
    // Bubble unexpected errors (network, 500, schema drift).
    throw error;
  }
}

// MediaError numeric codes (browser constants, defined here to avoid
// referencing the browser global so the function is testable in Vitest).
const MEDIA_ERR_NETWORK = 2;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4;

/**
 * Pure logic: given an HTMLAudioElement error event, decide whether a 403
 * retry is warranted.
 *
 * A stale Deezer preview URL returns HTTP 403 (MEDIA_ERR_NETWORK,
 * code=2 or MEDIA_ERR_SRC_NOT_SUPPORTED, code=4) rather than a normal
 * network error. We treat both as potentially-stale because the audio
 * element exposes no HTTP status code directly.
 */
export function isPreviewStaleError(
  mediaError: MediaError | null | undefined,
): boolean {
  if (!mediaError) return false;
  return (
    mediaError.code === MEDIA_ERR_NETWORK ||
    mediaError.code === MEDIA_ERR_SRC_NOT_SUPPORTED
  );
}

/**
 * Retry state: one-shot guard so we attempt the refresh exactly once per
 * play session, even if the fresh URL also errors.
 */
export interface PreviewRetryState {
  attempted: boolean;
}

export function initialRetryState(): PreviewRetryState {
  return { attempted: false };
}
