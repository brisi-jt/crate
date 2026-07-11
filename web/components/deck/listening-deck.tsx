"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useUndoJournal } from "@/hooks/api/use-journal";
import {
  useDiscoveryRun,
  useSuggestionFeedback,
  useSuggestions,
} from "@/hooks/api/use-suggestions";
import type { Suggestion } from "@/lib/api/schemas";
import { acousticColor, oklchString } from "@/lib/color/acoustic";
import { ghostFill, ghostOffset } from "@/lib/deck/ghost";
import { currentId } from "@/lib/deck/machine";
import { playbackMode, SpotifyPlayback } from "@/lib/playback/spotify-sdk";
import { useDeckStore } from "@/lib/store/deck";
import { usePlayerStore } from "@/lib/store/player";
import type { GhostRender } from "../graph/graph-canvas";

/** Fingerprint rows the deck compares against the playlist profile. */
const DECK_FEATURES: Array<{ key: string; label: string }> = [
  { key: "energy", label: "Energy" },
  { key: "valence", label: "Valence" },
  { key: "acousticness", label: "Acousticness" },
];

interface ListeningDeckProps {
  playlistId: number;
  playlistName: string;
  /** Target playlist's data color (header badge + fingerprint ticks). */
  playlistSwatch: string | null;
  /** Target node's rendered radius — anchors the ghost's offset. */
  targetRadius: number;
  onGhostChange: (ghost: GhostRender | null) => void;
  onClose: () => void;
}

function candidateCentroid(suggestion: Suggestion) {
  const byFeature = Object.fromEntries(
    suggestion.fingerprint.map((point) => [point.feature, point.candidate]),
  );
  return {
    energy: byFeature.energy ?? 0.5,
    valence: byFeature.valence ?? 0.5,
    acousticness: byFeature.acousticness ?? 0.5,
  };
}

function playlistCentroid(suggestion: Suggestion) {
  const byFeature = Object.fromEntries(
    suggestion.fingerprint.map((point) => [point.feature, point.playlist]),
  );
  return {
    energy: byFeature.energy ?? 0.5,
    valence: byFeature.valence ?? 0.5,
    acousticness: byFeature.acousticness ?? 0.5,
  };
}

export function ListeningDeck({
  playlistId,
  playlistName,
  playlistSwatch,
  targetRadius,
  onGhostChange,
  onClose,
}: ListeningDeckProps) {
  const suggestions = useSuggestions(playlistId);
  const feedback = useSuggestionFeedback(playlistId);
  const run = useDiscoveryRun(playlistId);
  const undo = useUndoJournal();

  const queue = useDeckStore((s) => s.queue);
  const index = useDeckStore((s) => s.index);
  const playing = useDeckStore((s) => s.playing);
  const dispatch = useDeckStore((s) => s.dispatch);

  const sdkRef = useRef<SpotifyPlayback | null>(null);

  const items = useMemo(
    () => suggestions.data?.items ?? [],
    [suggestions.data],
  );
  const byId = useMemo(
    () => new Map(items.map((item) => [item.id, item])),
    [items],
  );

  // Feed queue reloads into the machine (it follows the focused candidate).
  useEffect(() => {
    if (suggestions.data) {
      dispatch({ type: "LOADED", queue: items.map((item) => item.id) });
    }
  }, [suggestions.data, items, dispatch]);

  const current = useMemo(() => {
    const id = currentId({ queue, index, playing });
    return id === null ? null : (byId.get(id) ?? null);
  }, [queue, index, playing, byId]);

  const candidateSwatch = useMemo(
    () =>
      current ? oklchString(acousticColor(candidateCentroid(current))) : null,
    [current],
  );

  // The glowing ghost: candidate's acoustic position beside the target node.
  useEffect(() => {
    if (!current) {
      onGhostChange(null);
      return;
    }
    const color = acousticColor(candidateCentroid(current));
    onGhostChange({
      title: `${current.title} — ${current.artist}`,
      stroke: oklchString(color),
      fill: oklchString(ghostFill(color)),
      offset: ghostOffset(
        candidateCentroid(current),
        playlistCentroid(current),
        targetRadius,
      ),
      playing,
    });
    return () => onGhostChange(null);
  }, [current, playing, targetRadius, onGhostChange]);

  // Audio: play intent + current candidate -> the preview player (or SDK).
  // Player actions go through getState() so the deck never re-renders on
  // per-frame timeupdate ticks.
  const sdkEligible = Boolean(
    playbackMode() === "sdk" &&
      current?.spotify_id &&
      !current.spotify_id.startsWith("fake-"),
  );
  const lastAudioKey = useRef<string | null>(null);
  useEffect(() => {
    const player = usePlayerStore.getState();
    // Query refetches swap object identities without changing the audition;
    // only a genuine (candidate, intent) change may touch the audio element.
    const audioKey = current ? `${current.id}|${playing}` : "none";
    if (audioKey === lastAudioKey.current) return;
    lastAudioKey.current = audioKey;

    if (!current) {
      player.stop();
      return;
    }
    if (!playing) {
      player.pause();
      if (sdkEligible) void sdkRef.current?.pause();
      return;
    }
    if (sdkEligible && current.spotify_id) {
      const spotifyId = current.spotify_id;
      if (sdkRef.current === null) sdkRef.current = new SpotifyPlayback();
      const sdk = sdkRef.current;
      const start = async () => {
        if (!sdk.deviceId) await sdk.connect();
        await sdk.playTrack(spotifyId);
      };
      void start().catch(() => dispatch({ type: "AUDIO_ENDED" }));
      player.load({
        title: current.title,
        artist: current.artist,
        url: null,
        nodeId: playlistId,
        swatch: candidateSwatch,
        mode: "AUDITION · SPOTIFY",
      });
      return;
    }
    if (!current.preview_url) {
      // No audio for this candidate — the card shows the Spotify path.
      dispatch({ type: "AUDIO_ENDED" });
      return;
    }
    player.load({
      title: current.title,
      artist: current.artist,
      url: current.preview_url,
      nodeId: playlistId,
      swatch: candidateSwatch,
      mode: "AUDITION · PREVIEW 0:30",
    });
    player.play();
  }, [current, playing, sdkEligible, candidateSwatch, playlistId, dispatch]);

  // Preview end -> the machine's playing intent follows; unmount silences.
  useEffect(() => {
    usePlayerStore
      .getState()
      .setOnEnded(() => dispatch({ type: "AUDIO_ENDED" }));
    return () => {
      const player = usePlayerStore.getState();
      player.setOnEnded(null);
      player.stop();
      sdkRef.current?.disconnect();
    };
  }, [dispatch]);

  const accept = useCallback(
    (suggestion: Suggestion) => {
      feedback.mutate(
        { candidateId: suggestion.id, action: "accept" },
        {
          onSuccess: (result) => {
            const journalId = result.journal_id;
            toast(`Added ${suggestion.title} to ${playlistName}`, {
              duration: 8000,
              action:
                journalId === null
                  ? undefined
                  : {
                      label: "UNDO",
                      onClick: () => undo.mutate(journalId),
                    },
            });
          },
        },
      );
      dispatch({ type: "RESOLVE", id: suggestion.id });
    },
    [feedback, playlistName, undo, dispatch],
  );

  const reject = useCallback(
    (suggestion: Suggestion) => {
      feedback.mutate({ candidateId: suggestion.id, action: "reject" });
      dispatch({ type: "RESOLVE", id: suggestion.id });
    },
    [feedback, dispatch],
  );

  const skipForward = useCallback(
    (suggestion: Suggestion | null) => {
      if (suggestion) {
        feedback.mutate({ candidateId: suggestion.id, action: "skip" });
      }
      dispatch({ type: "NEXT" });
    },
    [feedback, dispatch],
  );

  // Keyboard-first review: space / a / x / j / k while the deck is open.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      switch (event.key) {
        case " ":
          event.preventDefault();
          if (current?.preview_url || sdkEligible) {
            dispatch({ type: "TOGGLE_PLAY" });
          }
          break;
        case "a":
          event.preventDefault();
          if (current) accept(current);
          break;
        case "x":
          event.preventDefault();
          if (current) reject(current);
          break;
        case "j":
          event.preventDefault();
          skipForward(current);
          break;
        case "k":
          event.preventDefault();
          dispatch({ type: "PREV" });
          break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [current, sdkEligible, dispatch, accept, reject, skipForward]);

  return (
    <section
      aria-label={`Listening deck — auditioning for ${playlistName}`}
      className="-translate-x-1/2 absolute bottom-[76px] left-1/2 z-30 flex w-[560px] flex-col gap-md rounded-md border border-border-subtle bg-surface-3 p-lg"
    >
      <div className="flex items-center gap-sm">
        <span className="micro-caps text-text-muted">Auditioning for</span>
        <span className="micro-caps flex items-center gap-2xs rounded-xs border border-border-subtle px-xs py-2xs text-text-secondary">
          <span
            className="inline-block size-[10px] rounded-xs"
            style={{ background: playlistSwatch ?? "var(--text-muted)" }}
          />
          {playlistName.toUpperCase()}
        </span>
        <span className="data-readout ml-auto text-micro text-text-muted">
          {queue.length === 0 ? "0 / 0" : `${index + 1} / ${queue.length}`}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="micro-caps cursor-pointer text-text-muted hover:text-text-secondary"
        >
          ESC
        </button>
      </div>

      {suggestions.isPending ? (
        <div className="flex flex-col gap-sm">
          <Skeleton className="h-[56px] w-full bg-surface-2" />
          <Skeleton className="h-[72px] w-full bg-surface-2" />
        </div>
      ) : current === null ? (
        <div className="flex flex-col items-center gap-sm py-lg">
          <p className="text-sm text-text-secondary">
            {items.length === 0
              ? "No suggestions queued for this playlist yet."
              : "Queue reviewed — every candidate has a verdict."}
          </p>
          <Button
            size="sm"
            variant="outline"
            disabled={run.isPending}
            onClick={() => run.mutate()}
            className="micro-caps border-border-subtle text-text-secondary"
          >
            {run.isPending ? "Running discovery…" : "Run discovery"}
          </Button>
        </div>
      ) : (
        <>
          <div className="flex items-start gap-md">
            <div
              className="data-readout flex size-[56px] flex-none items-center justify-center rounded-sm border border-border-subtle text-micro text-text-muted"
              style={{
                background: `color-mix(in oklch, ${candidateSwatch ?? "var(--surface-2)"} 30%, var(--surface-2))`,
              }}
            >
              ART
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate font-bold text-lg text-text-primary leading-snug">
                {current.title}
              </div>
              <div className="truncate text-sm text-text-secondary">
                {current.artist}
                {current.album_name ? ` · ${current.album_name}` : ""}
              </div>
            </div>
            <div className="flex flex-none flex-col items-end gap-2xs">
              <div className="flex items-baseline gap-xs">
                <span className="micro-caps text-text-muted">Fit</span>
                <span className="data-readout text-lg text-text-primary">
                  {current.fit.toFixed(2)}
                </span>
              </div>
              <span className="micro-caps rounded-xs border border-border-subtle px-xs py-2xs text-text-muted">
                via {current.source}
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-xs">
            {DECK_FEATURES.map(({ key, label }) => {
              const point = current.fingerprint.find((p) => p.feature === key);
              if (!point) return null;
              return (
                <div
                  key={key}
                  className="grid grid-cols-[110px_1fr_42px] items-center gap-sm"
                >
                  <span className="micro-caps text-text-muted">{label}</span>
                  <div className="relative h-[6px] rounded-xs bg-surface-2">
                    <div
                      className="h-[6px] rounded-xs"
                      style={{
                        width: `${Math.round(point.candidate * 100)}%`,
                        background: candidateSwatch ?? "var(--text-secondary)",
                      }}
                    />
                    {/* Playlist-profile tick — where the target sits on this axis */}
                    <div
                      className="absolute top-[-3px] h-[12px] w-[2px]"
                      style={{
                        left: `${Math.round(point.playlist * 100)}%`,
                        background: playlistSwatch ?? "var(--text-secondary)",
                      }}
                    />
                  </div>
                  <span className="data-readout text-right text-micro text-text-secondary">
                    P{Math.round(point.candidate * 100)}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="flex items-center gap-md text-sm text-text-muted">
            {current.preview_url || sdkEligible ? (
              <span className="flex items-center gap-2xs">
                <Kbd>space</Kbd> {playing ? "pause" : "play"}
              </span>
            ) : (
              <span className="flex items-center gap-2xs text-text-muted">
                NO PREVIEW
                {current._links?.spotify ? (
                  <a
                    href={current._links.spotify.href}
                    target="_blank"
                    rel="noreferrer"
                    className="micro-caps text-text-secondary underline underline-offset-2 hover:text-text-primary"
                  >
                    open in Spotify
                  </a>
                ) : null}
              </span>
            )}
            <span className="flex items-center gap-2xs">
              <Kbd>a</Kbd> add
            </span>
            <span className="flex items-center gap-2xs">
              <Kbd>x</Kbd> reject
            </span>
            <span className="flex items-center gap-2xs">
              <Kbd>j</Kbd>/<Kbd>k</Kbd> next / prev
            </span>
          </div>
        </>
      )}
    </section>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="data-readout rounded-xs border border-border-subtle bg-surface-2 px-xs py-[1px] text-micro text-text-secondary">
      {children}
    </kbd>
  );
}
