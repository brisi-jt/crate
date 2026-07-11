"use client";

import { useCallback, useRef } from "react";
import { useDeckStore } from "@/lib/store/deck";
import { usePlayerStore } from "@/lib/store/player";

/**
 * The always-present transport strip (56px, bottom): now-playing readout,
 * play/pause, scrub, volume. Preview playback drives it; while the listening
 * deck is open, prev/next steer the review queue. Clicking the artwork flies
 * the map to the playing track's playlist. Nothing may overlap this strip.
 */
export function TransportStrip({
  onArtworkClick,
}: {
  onArtworkClick?: (nodeId: number) => void;
}) {
  const current = usePlayerStore((s) => s.current);
  const playing = usePlayerStore((s) => s.playing);
  const position = usePlayerStore((s) => s.position);
  const duration = usePlayerStore((s) => s.duration);
  const volume = usePlayerStore((s) => s.volume);
  const toggle = usePlayerStore((s) => s.toggle);
  const seek = usePlayerStore((s) => s.seek);
  const setVolume = usePlayerStore((s) => s.setVolume);

  const deckOpen = useDeckStore((s) => s.playlistId !== null);
  const dispatch = useDeckStore((s) => s.dispatch);

  const hasAudio = current !== null && current.url !== null;
  const fraction = duration > 0 ? position / duration : 0;

  const scrubRef = useRef<HTMLDivElement>(null);
  const volumeRef = useRef<HTMLDivElement>(null);

  const railFraction = useCallback(
    (rail: HTMLDivElement | null, clientX: number): number => {
      if (!rail) return 0;
      const rect = rail.getBoundingClientRect();
      return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    },
    [],
  );

  return (
    <footer className="absolute right-0 bottom-0 left-0 z-30 flex h-[56px] items-center gap-md border-border-subtle border-t bg-surface-1 px-md">
      <button
        type="button"
        aria-label="Fly the map to the playing playlist"
        disabled={current?.nodeId == null}
        onClick={() => {
          if (current?.nodeId != null) onArtworkClick?.(current.nodeId);
        }}
        className="size-8 flex-none cursor-pointer rounded-xs border border-border-subtle bg-surface-2 disabled:cursor-default"
        style={current?.swatch ? { background: current.swatch } : undefined}
      />
      <div className="flex w-[210px] flex-col leading-tight">
        {current ? (
          <>
            <span className="truncate text-sm text-text-primary">
              {current.title} — {current.artist}
            </span>
            <span className="micro-caps text-text-muted">{current.mode}</span>
          </>
        ) : (
          <>
            <span className="text-sm text-text-secondary">Nothing playing</span>
            <span className="micro-caps text-text-muted">
              {deckOpen ? "DECK READY" : "NO DEVICE"}
            </span>
          </>
        )}
      </div>
      <div className="flex items-center gap-2xs">
        <TransportButton
          label="Previous candidate"
          disabled={!deckOpen}
          onClick={() => dispatch({ type: "PREV" })}
        >
          ⏮
        </TransportButton>
        <TransportButton
          label={playing ? "Pause" : "Play"}
          disabled={!hasAudio && !deckOpen}
          onClick={() => {
            if (deckOpen) dispatch({ type: "TOGGLE_PLAY" });
            else toggle();
          }}
        >
          {playing ? "⏸" : "▶"}
        </TransportButton>
        <TransportButton
          label="Next candidate"
          disabled={!deckOpen}
          onClick={() => dispatch({ type: "NEXT" })}
        >
          ⏭
        </TransportButton>
      </div>
      <div className="flex flex-1 items-center gap-sm">
        <span className="data-readout text-micro text-text-muted">
          {formatSeconds(position)}
        </span>
        {/* biome-ignore lint/a11y/useKeyWithClickEvents: scrubbing is pointer-driven; keyboard playback control lives on the transport buttons */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: the rail is a click-to-seek surface, not a focus stop */}
        <div
          ref={scrubRef}
          onClick={(event) =>
            hasAudio && seek(railFraction(scrubRef.current, event.clientX))
          }
          className="relative h-[3px] flex-1 cursor-pointer rounded-full bg-surface-3"
        >
          <div
            className="absolute top-0 bottom-0 left-0 rounded-full bg-text-secondary"
            style={{ width: `${fraction * 100}%` }}
          />
          {hasAudio && (
            <div
              className="-translate-y-1/2 -translate-x-1/2 absolute top-1/2 size-[9px] rounded-full bg-text-primary"
              style={{ left: `${fraction * 100}%` }}
            />
          )}
        </div>
        <span className="data-readout text-micro text-text-muted">
          {formatSeconds(duration)}
        </span>
      </div>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: pointer-driven volume rail */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: click-to-set surface */}
      <div
        ref={volumeRef}
        onClick={(event) =>
          setVolume(railFraction(volumeRef.current, event.clientX))
        }
        title="Volume"
        className="relative h-[3px] w-[90px] cursor-pointer rounded-full bg-surface-3"
      >
        <div
          className="absolute top-0 bottom-0 left-0 rounded-full bg-text-secondary"
          style={{ width: `${volume * 100}%` }}
        />
        <div
          className="-translate-y-1/2 -translate-x-1/2 absolute top-1/2 size-[9px] rounded-full bg-text-primary"
          style={{ left: `${volume * 100}%` }}
        />
      </div>
      <span className="micro-caps text-text-muted">
        {current ? "DESK · PREVIEW" : "IDLE"}
      </span>
    </footer>
  );
}

function TransportButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={label}
      onClick={onClick}
      className="cursor-pointer rounded-xs px-xs py-2xs text-[15px] text-text-secondary hover:bg-surface-2 hover:text-text-primary disabled:cursor-default disabled:text-text-muted disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

function formatSeconds(total: number): string {
  const seconds = Math.max(0, Math.floor(total));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
