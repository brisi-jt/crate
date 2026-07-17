/**
 * Maps the panel's source + ≤N slider into the /v1/triage/queue query params.
 * The slider is liked-mode only, so max_playlists is omitted in playlist mode
 * (the backend ignores it there) — keeping the sent params honest.
 */

export const TRIAGE_PAGE_SIZE = 50;

export interface QueueParamsInput {
  source: "liked" | "playlist";
  /** The ≤N-playlists slider value (liked mode only). */
  maxPlaylists: number;
  offset: number;
}

export interface QueueParams {
  limit: number;
  offset: number;
  max_playlists?: number;
}

export function queueParams(input: QueueParamsInput): QueueParams {
  const params: QueueParams = {
    limit: TRIAGE_PAGE_SIZE,
    offset: input.offset,
  };
  if (input.source === "liked") {
    params.max_playlists = Math.max(0, Math.trunc(input.maxPlaylists));
  }
  return params;
}
