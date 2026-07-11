"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Readout } from "@/components/panels/right-dock";
import { TargetPicker } from "@/components/panels/target-picker";
import { Separator } from "@/components/ui/separator";
import { useFrontier } from "@/hooks/api/use-frontier";
import { useUndoJournal } from "@/hooks/api/use-journal";
import { usePlaylists } from "@/hooks/api/use-playlists";
import {
  useCreateRadio,
  useRadio,
  useRadioItemFeedback,
} from "@/hooks/api/use-radio";
import { queryKeys } from "@/lib/api/keys";
import type { RadioItem, RadioSession } from "@/lib/api/schemas";
import {
  itemReadout,
  nextPlayableIndex,
  sessionComplete,
  sessionSummary,
} from "@/lib/radio/logic";
import { usePlayerStore } from "@/lib/store/player";

/**
 * Playlist radio: seed a session from a playlist or a frontier genre, then
 * work the ordered tracklist — the transport strip plays each row's preview,
 * keep/skip verdicts feed the discovery ranker, and keeping a candidate can
 * journal it straight into the seed playlist.
 */
export function RadioPanelContent() {
  const [sessionId, setSessionId] = useState<number | null>(null);

  if (sessionId === null) {
    return <SeedStage onStarted={setSessionId} />;
  }
  return (
    <SessionStage sessionId={sessionId} onNewSeed={() => setSessionId(null)} />
  );
}

// ------------------------------------------------------------------- seeding

function SeedStage({ onStarted }: { onStarted: (id: number) => void }) {
  const playlists = usePlaylists();
  const frontier = useFrontier();
  const create = useCreateRadio();
  const queryClient = useQueryClient();
  const [playlistId, setPlaylistId] = useState<number | null>(null);
  const [genreId, setGenreId] = useState<number | null>(null);

  const playlistOptions = useMemo(
    () =>
      playlists.data?.items
        .filter((p) => !p.is_deleted && p.is_owned)
        .map((p) => ({ id: p.id, name: p.name })) ?? [],
    [playlists.data],
  );
  const genreOptions = useMemo(
    () =>
      frontier.data?.frontier.map((genre) => ({
        id: genre.genre_id,
        name: genre.name,
      })) ?? [],
    [frontier.data],
  );
  const genreName =
    genreOptions.find((option) => option.id === genreId)?.name ?? null;

  const start = () => {
    const seed =
      playlistId !== null
        ? { playlistId }
        : genreName !== null
          ? { genre: genreName }
          : null;
    if (seed === null) return;
    create.mutate(seed, {
      onSuccess: (session) => {
        queryClient.setQueryData(queryKeys.radio(session.id), session);
        onStarted(session.id);
      },
    });
  };

  return (
    <>
      <p className="max-w-[52ch] text-sm text-text-secondary">
        A radio session gathers ~25 tracks around one seed — library material
        ordered for harmonic and tempo flow, with discovery candidates dropped
        in about one slot in five.
      </p>

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">Seed — playlist</span>
        <TargetPicker
          options={playlistOptions}
          value={playlistId}
          onPick={(id) => {
            setPlaylistId(id);
            setGenreId(null);
          }}
          placeholder="PICK A PLAYLIST"
        />
      </section>

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">
          Seed — frontier genre
        </span>
        {genreOptions.length === 0 ? (
          <span className="text-sm text-text-secondary">
            No frontier genres yet — the frontier explorer charts them once the
            atlas knows the library.
          </span>
        ) : (
          <TargetPicker
            options={genreOptions}
            value={genreId}
            onPick={(id) => {
              setGenreId(id);
              setPlaylistId(null);
            }}
            placeholder="PICK A GENRE"
            emptyNote="No frontier genres yet."
          />
        )}
      </section>

      <Separator />

      <div className="flex items-center gap-md">
        <button
          type="button"
          disabled={
            (playlistId === null && genreId === null) || create.isPending
          }
          onClick={start}
          className="display-caps cursor-pointer rounded-sm bg-amber px-md py-2xs text-amber-ink text-micro transition-colors duration-150 hover:bg-amber-press disabled:cursor-default disabled:opacity-45"
        >
          {create.isPending ? "Tuning…" : "Start radio"}
        </button>
        {create.isError && (
          <span className="micro-caps text-danger">
            NOTHING TO PLAY FROM THAT SEED · TRY ANOTHER
          </span>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------- session

function SessionStage({
  sessionId,
  onNewSeed,
}: {
  sessionId: number;
  onNewSeed: () => void;
}) {
  const radio = useRadio(sessionId);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  if (radio.isPending) {
    return <span className="micro-caps text-text-muted">TUNING…</span>;
  }
  if (radio.isError || !radio.data) {
    return (
      <div className="flex flex-col items-start gap-xs">
        <span className="micro-caps text-danger">SESSION UNAVAILABLE</span>
        <button
          type="button"
          onClick={onNewSeed}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Pick a new seed
        </button>
      </div>
    );
  }

  return (
    <SessionView
      session={radio.data}
      activeIndex={activeIndex}
      onActiveIndex={setActiveIndex}
      onNewSeed={onNewSeed}
    />
  );
}

function SessionView({
  session,
  activeIndex,
  onActiveIndex,
  onNewSeed,
}: {
  session: RadioSession;
  activeIndex: number | null;
  onActiveIndex: (index: number | null) => void;
  onNewSeed: () => void;
}) {
  const player = usePlayerStore();
  const summary = sessionSummary(session.items);
  const complete = sessionComplete(session.items);

  // Refs keep the auto-advance handler honest across re-renders.
  const itemsRef = useRef(session.items);
  itemsRef.current = session.items;
  const activeRef = useRef(activeIndex);
  activeRef.current = activeIndex;

  const playIndex = useMemo(() => {
    return (index: number) => {
      const items = itemsRef.current;
      const target = nextPlayableIndex(items, index);
      if (target === null) {
        onActiveIndex(null);
        return;
      }
      const item = items[target];
      onActiveIndex(target);
      activeRef.current = target;
      usePlayerStore.getState().load({
        title: item.title,
        artist: item.artist,
        url: item.preview_url,
        nodeId: session.seed_playlist_id,
        swatch: null,
        mode: "RADIO · PREVIEW 0:30",
      });
      usePlayerStore.getState().play();
    };
  }, [onActiveIndex, session.seed_playlist_id]);

  // Auto-advance: when a preview ends, the run moves to the next playable row.
  useEffect(() => {
    usePlayerStore.getState().setOnEnded(() => {
      const current = activeRef.current;
      if (current !== null) playIndex(current + 1);
    });
    return () => usePlayerStore.getState().setOnEnded(null);
  }, [playIndex]);

  return (
    <>
      <div className="flex items-end gap-xl">
        <Readout label="Session" value={session.label.toUpperCase()} />
        <Readout label="Kept" value={String(summary.kept)} />
        <Readout label="Skipped" value={String(summary.skipped)} />
        <Readout label="Queued" value={String(summary.pending)} />
        <button
          type="button"
          onClick={onNewSeed}
          className="micro-caps ml-auto cursor-pointer text-text-muted hover:text-text-primary"
        >
          NEW SEED
        </button>
      </div>

      {complete && (
        <div className="flex flex-col gap-2xs rounded-md border border-border-subtle border-dashed px-md py-sm">
          <span className="micro-caps text-text-muted">Session complete</span>
          <span className="data-readout text-sm text-text-primary">
            KEPT {summary.kept} · ADDED {summary.added} · SKIPPED{" "}
            {summary.skipped}
          </span>
        </div>
      )}

      <Separator />

      <div className="flex flex-col">
        {session.items.map((item, index) => (
          <RadioItemRow
            key={item.id}
            session={session}
            item={item}
            active={index === activeIndex}
            playing={index === activeIndex && player.playing}
            onPlay={() => {
              if (index === activeIndex) {
                usePlayerStore.getState().toggle();
              } else {
                playIndex(index);
              }
            }}
          />
        ))}
      </div>
    </>
  );
}

function RadioItemRow({
  session,
  item,
  active,
  playing,
  onPlay,
}: {
  session: RadioSession;
  item: RadioItem;
  active: boolean;
  playing: boolean;
  onPlay: () => void;
}) {
  const feedback = useRadioItemFeedback(session.id);
  const undo = useUndoJournal();
  const readout = itemReadout(item);
  const decided = item.feedback !== null;

  const keepAndAdd = () => {
    if (session.seed_playlist_id === null) return;
    feedback.mutate(
      {
        itemId: item.id,
        action: "keep",
        addToPlaylistId: session.seed_playlist_id,
      },
      {
        onSuccess: (updated) => {
          if (updated.journal_id !== null) {
            const journalId = updated.journal_id;
            toast(`Added ${item.title} to ${session.label}`, {
              action: { label: "UNDO", onClick: () => undo.mutate(journalId) },
            });
          }
        },
      },
    );
  };

  return (
    <div
      className={`flex items-center gap-sm border-border-subtle border-b px-2xs py-xs last:border-b-0 ${
        active ? "bg-surface-2" : ""
      }`}
    >
      <span className="data-readout w-[24px] text-micro text-text-muted">
        {String(item.position + 1).padStart(2, "0")}
      </span>
      <button
        type="button"
        onClick={onPlay}
        disabled={!item.preview_url}
        aria-label={playing ? `Pause ${item.title}` : `Play ${item.title}`}
        className="data-readout w-[20px] cursor-pointer text-sm text-text-secondary hover:text-text-primary disabled:cursor-default disabled:opacity-35"
      >
        {playing ? "❚❚" : "▶"}
      </button>
      <div className="flex min-w-0 flex-1 flex-col">
        <span
          className={`truncate text-sm ${
            item.feedback === "skipped"
              ? "text-text-muted line-through"
              : "text-text-primary"
          }`}
        >
          {item.title}
          <span className="text-text-secondary"> — {item.artist}</span>
        </span>
        <span className="flex items-center gap-sm text-micro text-text-muted">
          {readout && <span className="data-readout">{readout}</span>}
          {item.kind === "discovery" && (
            <span className="data-readout rounded-xs bg-surface-2 px-2xs text-text-secondary">
              DISCOVERY
            </span>
          )}
          {!item.preview_url && <span>NO PREVIEW</span>}
        </span>
      </div>
      {decided ? (
        <span className="data-readout shrink-0 text-micro text-text-muted">
          {item.journal_id !== null
            ? "ADDED ✓"
            : item.feedback === "kept"
              ? "KEPT ✓"
              : "SKIPPED"}
        </span>
      ) : (
        <div className="flex shrink-0 items-center gap-2xs">
          <button
            type="button"
            disabled={feedback.isPending}
            onClick={() => feedback.mutate({ itemId: item.id, action: "keep" })}
            className="micro-caps cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-text-secondary hover:text-text-primary disabled:opacity-45"
          >
            KEEP
          </button>
          {item.kind === "discovery" && session.seed_playlist_id !== null && (
            <button
              type="button"
              disabled={feedback.isPending}
              onClick={keepAndAdd}
              className="micro-caps cursor-pointer rounded-sm border border-border-strong px-sm py-2xs text-text-primary hover:bg-surface-2 disabled:opacity-45"
            >
              +ADD
            </button>
          )}
          <button
            type="button"
            disabled={feedback.isPending}
            onClick={() => feedback.mutate({ itemId: item.id, action: "skip" })}
            className="micro-caps cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-text-muted hover:text-text-primary disabled:opacity-45"
          >
            SKIP
          </button>
        </div>
      )}
    </div>
  );
}
