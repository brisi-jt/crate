"use client";

import { useSyncStatus, useTriggerSync } from "@/hooks/api/use-sync";
import type { GraphResponse } from "@/lib/api/schemas";

const API_BASE =
  process.env.NEXT_PUBLIC_CRATE_API_URL ?? "http://localhost:8200";

function formatTime(iso: string | null): string {
  if (!iso) return "NEVER";
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Field-manual sync chrome, woven directly onto the canvas margin (graph
 * spec §9) — no bar, no card. Degraded states read in --signal-danger with an
 * inline recovery action; never a modal.
 */
export function SyncReadout({ graph }: { graph: GraphResponse | null }) {
  const status = useSyncStatus();
  const sync = useTriggerSync();

  const connectHref = `${API_BASE}/v1/auth/spotify/connect`;

  if (status.isError) {
    return (
      <div className="micro-caps pointer-events-auto text-danger">
        API UNREACHABLE ·{" "}
        <button
          type="button"
          className="cursor-pointer underline"
          onClick={() => status.refetch()}
        >
          RETRY
        </button>
      </div>
    );
  }

  if (!status.data) {
    return (
      <div className="micro-caps pointer-events-none text-text-muted">
        SYNC — · CONNECTING
      </div>
    );
  }

  const s = status.data;
  const coverage = graph?.coverage ?? null;
  const coverageIncomplete =
    coverage !== null && coverage.enriched_tracks < coverage.total_tracks;

  return (
    <div className="pointer-events-auto flex items-center gap-md">
      {s.needs_reauth ? (
        <span className="micro-caps text-danger">
          SPOTIFY REAUTH REQUIRED ·{" "}
          <a className="underline" href={connectHref}>
            RECONNECT
          </a>
        </span>
      ) : !s.spotify_connected ? (
        <span className="micro-caps text-text-muted">
          SPOTIFY NOT CONNECTED ·{" "}
          <a className="text-amber underline" href={connectHref}>
            CONNECT
          </a>
        </span>
      ) : (
        <span className="micro-caps text-text-muted">
          SYNC {formatTime(s.last_synced_at)} · {s.playlist_count} PL
          {coverage && <> · {coverage.total_tracks.toLocaleString()} TRK</>}
        </span>
      )}

      {coverageIncomplete && coverage && (
        <span
          className="micro-caps text-text-muted"
          title="Tracks with acoustic features — grey nodes fill in as enrichment completes"
        >
          FEATURES {coverage.enriched_tracks.toLocaleString()}/
          {coverage.total_tracks.toLocaleString()}
        </span>
      )}

      {sync.isError && (
        <span className="micro-caps text-danger">SYNC FAILED</span>
      )}

      {s.spotify_connected && !s.needs_reauth && (
        <button
          type="button"
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
          className="micro-caps cursor-pointer text-text-secondary hover:text-text-primary disabled:cursor-default disabled:text-text-muted"
        >
          {sync.isPending ? "SYNCING…" : "SYNC NOW"}
        </button>
      )}
    </div>
  );
}
