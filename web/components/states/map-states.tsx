"use client";

import { Skeleton } from "@/components/ui/skeleton";

const API_BASE =
  process.env.NEXT_PUBLIC_CRATE_API_URL ?? "http://localhost:8200";

/**
 * First-run pre-sync state: an empty map with a single beacon — the empty
 * state teaches the interface (the one primary amber action on screen).
 */
export function ConnectBeacon() {
  return (
    <BeaconShell caption="No library yet. Connect Spotify and run the first sync — every playlist becomes a star on this map.">
      <a
        href={`${API_BASE}/v1/auth/spotify/connect`}
        className="display-caps rounded-sm bg-amber px-lg py-sm text-amber-ink text-micro transition-colors duration-150 hover:bg-amber-press"
      >
        Connect &amp; sync
      </a>
    </BeaconShell>
  );
}

/** Connected but nothing synced yet: the beacon becomes the sync trigger. */
export function FirstSyncBeacon({
  onSync,
  syncing,
}: {
  onSync: () => void;
  syncing: boolean;
}) {
  return (
    <BeaconShell caption="Spotify is connected. Run the first sync to pull your playlists onto the map.">
      <button
        type="button"
        onClick={onSync}
        disabled={syncing}
        className="display-caps cursor-pointer rounded-sm bg-amber px-lg py-sm text-amber-ink text-micro transition-colors duration-150 hover:bg-amber-press disabled:cursor-default disabled:opacity-45"
      >
        {syncing ? "Syncing…" : "Run first sync"}
      </button>
    </BeaconShell>
  );
}

function BeaconShell({
  caption,
  children,
}: {
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-md">
      {children}
      <p className="max-w-[42ch] text-center text-sm text-text-secondary">
        {caption}
      </p>
    </div>
  );
}

/** Sync pass running: skeleton constellation while the library lands. */
export function SyncInProgress() {
  const dots = [
    { left: "28%", top: "38%", size: 28 },
    { left: "42%", top: "55%", size: 36 },
    { left: "55%", top: "32%", size: 44 },
    { left: "66%", top: "58%", size: 32 },
    { left: "74%", top: "40%", size: 24 },
  ];
  return (
    <div className="absolute inset-0">
      {dots.map((dot) => (
        <Skeleton
          key={dot.left}
          className="absolute rounded-full bg-surface-2"
          style={{
            left: dot.left,
            top: dot.top,
            width: dot.size,
            height: dot.size,
          }}
        />
      ))}
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="micro-caps text-text-muted">
          SYNC PASS RUNNING · PLAYLISTS INBOUND
        </span>
      </div>
    </div>
  );
}

/** The graph endpoint exists but hasn't been computed for this library yet. */
export function MapNotComputed() {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-xs">
      <span className="micro-caps text-text-muted">MAP NOT COMPUTED</span>
      <p className="max-w-[46ch] text-center text-sm text-text-secondary">
        The analytics engine hasn't built the playlist graph yet. It runs after
        each sync — check back shortly.
      </p>
    </div>
  );
}

/** API unreachable / server error while loading the map. */
export function MapError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-xs">
      <span className="micro-caps text-danger">MAP UNAVAILABLE</span>
      <p className="max-w-[52ch] text-center text-sm text-text-secondary">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
      >
        Retry
      </button>
    </div>
  );
}
