"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import { BarRow } from "@/components/insights/extended/extended-kit";
import type { Obscurity } from "@/lib/api/schemas-competitive";
import {
  formatObscurity,
  obscurityLean,
} from "@/lib/competitive/dashboard-view";

/**
 * F3 — obscurity. Library headline plus the most-obscure playlists. Last.fm
 * listener counts aren't wired yet (no key), so a quiet pending note is honest
 * rather than a fabricated number.
 */
export function ObscuritySection({ data }: { data: Obscurity }) {
  const scored = data.playlists.filter((p) => p.score !== null);
  // Most obscure first, then most tracks — the api already orders most-obscure
  // first, but re-sort defensively for a stable view.
  const ranked = [...scored].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  const mostObscure = ranked.slice(0, 6);
  const mostMainstream = [...ranked].reverse().slice(0, 6);

  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap items-end gap-xl">
        <ExplainReadout
          metric="obscurity_library"
          label="Library"
          value={formatObscurity(data.library.score)}
        />
        <div className="flex flex-col gap-2xs">
          <span className="micro-caps text-text-muted">Lean</span>
          <span className="data-readout text-lg text-text-primary capitalize">
            {obscurityLean(data.library.score)}
          </span>
        </div>
        <div className="flex flex-col gap-2xs">
          <span className="micro-caps text-text-muted">Scored</span>
          <span className="data-readout text-lg text-text-primary">
            {data.library.scored_tracks.toLocaleString()}
          </span>
        </div>
      </div>

      {data.lastfm_pending && (
        <p className="max-w-[56ch] text-sm text-text-muted">
          Scored from genre rank today. Real listener counts sharpen this once a
          Last.fm key is connected.
        </p>
      )}

      {mostObscure.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="obscurity_playlist">
            <span className="micro-caps text-text-muted">
              Deepest cuts — most obscure playlists
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {mostObscure.map((p) => (
              <BarRow
                key={p.playlist_id}
                label={p.name}
                fraction={p.score ?? 0}
                value={formatObscurity(p.score)}
                accent
              />
            ))}
          </div>
        </div>
      )}

      {mostMainstream.length > 0 && (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">
            Most mainstream playlists
          </span>
          <div className="flex flex-col gap-2xs">
            {mostMainstream.map((p) => (
              <BarRow
                key={p.playlist_id}
                label={p.name}
                fraction={p.score ?? 0}
                value={formatObscurity(p.score)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
