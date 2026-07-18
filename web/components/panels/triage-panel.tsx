"use client";

import {
  Check,
  Heart,
  ListPlus,
  Music4,
  Plus,
  Settings2,
  SkipForward,
  Sparkles,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { toast } from "sonner";
import { Explain } from "@/components/explain/explain";
import { Readout } from "@/components/panels/right-dock";
import { TriageDestinationsView } from "@/components/panels/triage-destinations-view";
import { TriageRemovalPopup } from "@/components/panels/triage-removal-popup";
import { SourcePicker } from "@/components/panels/triage-source-picker";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { useUndoJournal } from "@/hooks/api/use-journal";
import {
  useOwnedPlaylists,
  useSetTriageSource,
  useTriageApply,
  useTriageDestinations,
  useTriageIntelligence,
  useTriageQueue,
  useTriageSetting,
} from "@/hooks/api/use-triage";
import { ApiError } from "@/lib/api/errors";
import type {
  DestinationSuggestion,
  NewCategory,
  QueueTrack,
  TriageMembership,
} from "@/lib/api/schemas";
import { refreshPreviewUrl } from "@/lib/playback/preview-refresh";
import { usePlayerStore } from "@/lib/store/player";
import { evidenceRows } from "@/lib/triage/evidence";
import {
  currentTrackId,
  initialTriageState,
  reduceTriage,
} from "@/lib/triage/machine";
import { TRIAGE_PAGE_SIZE } from "@/lib/triage/queue-params";
import {
  applyBody,
  canApply,
  emptySelection,
  reduceSelection,
} from "@/lib/triage/selection";

/**
 * The triage ritual: flip between Liked Songs (with a ≤N-playlists filter) and
 * a designated playlist, listen to the oldest-waiting song, read three labeled
 * intelligence panels, file it into playlists (or seed a new one) in one
 * journaled action, then confirm which songs to remove from the source.
 */
export function TriagePanelContent() {
  const setting = useTriageSetting();

  if (setting.isPending) {
    return <SourceSkeleton />;
  }
  if (setting.isError || !setting.data) {
    return (
      <PanelError
        message={
          setting.error instanceof Error
            ? setting.error.message
            : "Couldn't load the triage source."
        }
        onRetry={() => setting.refetch()}
      />
    );
  }

  return <TriageBody source={setting.data.source} setting={setting.data} />;
}

// ------------------------------------------------------------------ the body

function TriageBody({
  source,
  setting,
}: {
  source: "liked" | "playlist";
  setting: { playlist_id: number | null; playlist_name?: string | null };
}) {
  const [maxPlaylists, setMaxPlaylists] = useState(0);
  const [offset, setOffset] = useState(0);
  const [managing, setManaging] = useState(false);
  const [triage, dispatch] = useReducer(reduceTriage, initialTriageState);

  const queue = useTriageQueue({ source, maxPlaylists, offset });

  // Feed each loaded page into the machine, preserving focus. A source/filter
  // switch resets the machine (offset back to 0); a next page appends.
  const loadedKey = `${source}:${maxPlaylists}`;
  const prevKeyRef = useRef(loadedKey);
  const seenOffsetRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (prevKeyRef.current !== loadedKey) {
      prevKeyRef.current = loadedKey;
      seenOffsetRef.current = new Set();
      setOffset(0);
    }
  }, [loadedKey]);

  useEffect(() => {
    if (!queue.data) return;
    const ids = queue.data.items.map((t) => t.track_id);
    const marker = `${loadedKey}:${queue.data.offset}`;
    if (queue.data.offset === 0) {
      dispatch({ type: "LOADED", queue: ids });
      seenOffsetRef.current = new Set([marker]);
    } else if (!seenOffsetRef.current.has(marker)) {
      seenOffsetRef.current.add(marker);
      dispatch({ type: "APPENDED", queue: ids });
    }
  }, [queue.data, loadedKey]);

  const trackId = currentTrackId(triage);
  const total = queue.data?.total ?? 0;
  const loaded = triage.queue.length;

  // The full track catalog for the loaded pages (name lookup for the card).
  const trackById = useMemo(() => {
    const map = new Map<number, QueueTrack>();
    for (const item of queue.data?.items ?? []) map.set(item.track_id, item);
    return map;
  }, [queue.data]);

  // Pull the next page when the machine nears the tail of what it has.
  useEffect(() => {
    if (!queue.data) return;
    const nearTail = triage.index >= loaded - 3;
    const more = loaded < total;
    if (nearTail && more && !queue.isFetching) {
      setOffset((o) =>
        o + TRIAGE_PAGE_SIZE < total ? o + TRIAGE_PAGE_SIZE : o,
      );
    }
  }, [triage.index, loaded, total, queue.data, queue.isFetching]);

  const queueBody = queue.isPending ? (
    <QueueSkeleton />
  ) : queue.isError ? (
    <PanelError
      message={
        queue.error instanceof Error
          ? queue.error.message
          : "Couldn't load the queue."
      }
      onRetry={() => queue.refetch()}
    />
  ) : triage.drained || (total === 0 && loaded === 0) ? (
    <QueueDrained source={source} filtered={source === "liked"} />
  ) : trackId === null ? (
    <QueueSkeleton />
  ) : (
    <SongStage
      key={trackId}
      source={source}
      sourcePlaylistId={setting.playlist_id}
      trackId={trackId}
      track={trackById.get(trackId) ?? null}
      maxPlaylists={maxPlaylists}
      total={total}
      position={triage.index}
      onSkip={() => dispatch({ type: "SKIP" })}
      onApplied={() => dispatch({ type: "APPLIED", trackId })}
    />
  );

  return (
    <>
      <SourceControls
        source={source}
        setting={setting}
        maxPlaylists={maxPlaylists}
        onMaxPlaylists={setMaxPlaylists}
        onManageDestinations={() => setManaging(true)}
      />

      <Separator />

      {managing ? (
        <TriageDestinationsView onDone={() => setManaging(false)} />
      ) : (
        <>
          {source === "liked" && setting.playlist_id === null && (
            <OnboardingBanner />
          )}
          {queueBody}
        </>
      )}
    </>
  );
}

// -------------------------------------------------------------- source header

function SourceControls({
  source,
  setting,
  maxPlaylists,
  onMaxPlaylists,
  onManageDestinations,
}: {
  source: "liked" | "playlist";
  setting: { playlist_id: number | null; playlist_name?: string | null };
  maxPlaylists: number;
  onMaxPlaylists: (n: number) => void;
  onManageDestinations: () => void;
}) {
  const owned = useOwnedPlaylists();
  const destinations = useTriageDestinations();
  const setSource = useSetTriageSource();

  const excludedById = useMemo(() => {
    const map = new Map<number, boolean>();
    for (const d of destinations.data?.items ?? [])
      map.set(d.id, d.triage_excluded);
    return map;
  }, [destinations.data]);

  const options = useMemo(
    () =>
      owned.data?.map((p) => ({
        id: p.id,
        name: p.name || "Untitled",
        excluded: excludedById.get(p.id) ?? false,
      })) ?? [],
    [owned.data, excludedById],
  );

  return (
    <section className="flex flex-col gap-md">
      <div className="flex items-center justify-between">
        <Explain metric="triage_source">
          <span className="micro-caps text-text-muted">Triage source</span>
        </Explain>
        <button
          type="button"
          onClick={onManageDestinations}
          aria-label="Manage filing destinations"
          className="flex cursor-pointer items-center gap-2xs rounded-sm border border-border-subtle px-sm py-2xs text-micro text-text-muted hover:text-text-primary"
        >
          <Settings2 className="size-[13px]" /> Destinations
        </button>
      </div>
      <div className="flex items-center gap-2xs rounded-md border border-border-subtle bg-surface-2 p-2xs">
        <SegmentButton
          active={source === "liked"}
          onClick={() =>
            source !== "liked" && setSource.mutate({ source: "liked" })
          }
        >
          <Heart className="size-[13px]" /> Liked Songs
        </SegmentButton>
        <SegmentButton
          active={source === "playlist"}
          disabled={setting.playlist_id === null}
          onClick={() =>
            setting.playlist_id !== null &&
            source !== "playlist" &&
            setSource.mutate({
              source: "playlist",
              playlistId: setting.playlist_id,
            })
          }
        >
          <ListPlus className="size-[13px] rotate-180" />{" "}
          {setting.playlist_name ?? "Triage playlist"}
        </SegmentButton>
      </div>

      <div className="flex items-center gap-sm">
        <span className="micro-caps text-text-muted">Set triage playlist</span>
        <SourcePicker
          options={options}
          value={setting.playlist_id}
          onPick={(id) =>
            setSource.mutate({ source: "playlist", playlistId: id })
          }
        />
        {setSource.isError && setSource.error instanceof ApiError && (
          <span className="micro-caps text-danger">
            {setSource.error.problem?.error_code === "INVALID_TRIAGE_PLAYLIST"
              ? "NOT A LIVE OWNED PLAYLIST"
              : "COULDN'T SET SOURCE"}
          </span>
        )}
      </div>

      {source === "liked" && (
        <div className="flex flex-col gap-2xs">
          <div className="flex items-center justify-between">
            <Explain metric="orphan_filter">
              <span className="micro-caps text-text-muted">
                Show songs in ≤ N playlists
              </span>
            </Explain>
            <span className="data-readout text-micro text-text-secondary">
              N = {maxPlaylists}
              {maxPlaylists === 0 ? " · orphans" : ""}
            </span>
          </div>
          <Slider
            value={[maxPlaylists]}
            min={0}
            max={10}
            step={1}
            onValueChange={([n]) => onMaxPlaylists(n)}
            aria-label="Maximum playlists a song may already be in"
          />
        </div>
      )}
    </section>
  );
}

function SegmentButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`micro-caps flex flex-1 cursor-pointer items-center justify-center gap-2xs rounded-sm px-sm py-xs transition-colors ${
        active
          ? "bg-amber text-amber-ink"
          : "text-text-secondary hover:text-text-primary"
      } disabled:cursor-default disabled:opacity-40`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- song stage

function SongStage({
  source,
  sourcePlaylistId,
  trackId,
  track,
  maxPlaylists,
  total,
  position,
  onSkip,
  onApplied,
}: {
  source: "liked" | "playlist";
  sourcePlaylistId: number | null;
  trackId: number;
  track: QueueTrack | null;
  maxPlaylists: number;
  total: number;
  position: number;
  onSkip: () => void;
  onApplied: () => void;
}) {
  const intel = useTriageIntelligence({ trackId, maxPlaylists });
  const apply = useTriageApply();
  const undo = useUndoJournal();
  const [selection, dispatchSel] = useReducer(
    reduceSelection,
    emptySelection(),
  );
  const [popup, setPopup] = useState<{ trackIds: number[] } | null>(null);

  const player = usePlayerStore();
  const playing =
    player.playing && player.current?.title === (track?.name ?? "");

  // Preview playback for the queued song (no stored URL — refresh on demand,
  // reusing the 403-retry helper already in the codebase).
  const playSong = async () => {
    if (playing) {
      usePlayerStore.getState().pause();
      return;
    }
    try {
      const url = await refreshPreviewUrl({ track_id: trackId });
      if (!url) {
        toast("No preview available for this track.");
        return;
      }
      usePlayerStore.getState().load({
        title: track?.name ?? "Track",
        artist: "",
        url,
        nodeId: null,
        swatch: null,
        mode: "TRIAGE · PREVIEW 0:30",
      });
      usePlayerStore.getState().play();
    } catch {
      toast.error("Couldn't fetch a preview.");
    }
  };

  const runApply = () => {
    const body = applyBody(selection, trackId);
    apply.mutate(body, {
      onSuccess: (result) => {
        const journalId = result.journal_id;
        toast("Filed.", {
          action: { label: "UNDO", onClick: () => undo.mutate(journalId) },
        });
        // Offer the removal popup: the just-filed song is the removal candidate.
        setPopup({ trackIds: [trackId] });
        dispatchSel({ type: "RESET" });
      },
      onError: (error) => {
        const code =
          error instanceof ApiError ? error.problem?.error_code : undefined;
        if (code === "SPOTIFY_NOT_CONNECTED" || code === "REAUTH_REQUIRED") {
          toast.error("Spotify session expired — reconnect Spotify.");
          return;
        }
        toast.error(error instanceof Error ? error.message : "Apply failed");
      },
    });
  };

  return (
    <>
      <div className="flex items-start justify-between gap-md">
        <div className="flex min-w-0 flex-col gap-2xs">
          <span className="micro-caps text-text-muted">Now triaging</span>
          <h3 className="truncate font-medium text-lg text-text-primary">
            {track?.name ?? `Track ${trackId}`}
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-sm">
          <button
            type="button"
            onClick={playSong}
            aria-label={playing ? "Pause preview" : "Play preview"}
            className="data-readout cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-sm text-text-secondary hover:text-text-primary"
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <Readout
            label="Queue"
            value={`${Math.min(position + 1, total)} / ${total}`}
          />
        </div>
      </div>

      <div className="flex items-center gap-sm">
        <button
          type="button"
          disabled={!canApply(selection) || apply.isPending}
          onClick={runApply}
          className="display-caps cursor-pointer rounded-sm bg-amber px-md py-xs text-amber-ink text-micro transition-colors hover:bg-amber-press disabled:cursor-default disabled:opacity-40"
        >
          {apply.isPending ? "Filing…" : "File this song"}
        </button>
        <button
          type="button"
          onClick={onSkip}
          className="micro-caps flex cursor-pointer items-center gap-2xs rounded-sm border border-border-subtle px-md py-xs text-text-muted hover:text-text-primary"
        >
          <SkipForward className="size-[13px]" /> Skip
        </button>
      </div>

      <Separator />

      {intel.isPending ? (
        <IntelligenceSkeleton />
      ) : intel.isError || !intel.data ? (
        <PanelError
          message={
            intel.error instanceof Error
              ? intel.error.message
              : "Couldn't load intelligence for this song."
          }
          onRetry={() => intel.refetch()}
        />
      ) : (
        <>
          <MembershipsPanel memberships={intel.data.memberships} />
          <SuggestionsPanel
            suggestions={intel.data.suggestions}
            selectedIds={selection.destinationIds}
            onToggle={(id) =>
              dispatchSel({ type: "TOGGLE_DEST", playlistId: id })
            }
          />
          <NewCategoryPanel
            newCategory={intel.data.new_category}
            filedTrackId={trackId}
            draft={selection.newPlaylist}
            hasStrongFit={hasStrongFit(intel.data.suggestions)}
            onSet={(draft) =>
              dispatchSel({ type: "SET_NEW_PLAYLIST", newPlaylist: draft })
            }
          />
        </>
      )}

      <AnimatePresence>
        {popup && (
          <TriageRemovalPopup
            source={source}
            sourcePlaylistId={sourcePlaylistId}
            songs={popup.trackIds.map((id) => ({
              trackId: id,
              name:
                id === trackId ? (track?.name ?? `Track ${id}`) : `Track ${id}`,
            }))}
            onClose={() => {
              setPopup(null);
              onApplied();
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}

function hasStrongFit(suggestions: DestinationSuggestion[]): boolean {
  // Strong existing fit = a top suggestion the song is not already in with a
  // clearly-leading rank; keeps the new-category card quiet in that case.
  const best = suggestions.find((s) => !s.already_in);
  return best !== undefined && best.rank >= 0.5;
}

// ------------------------------------------------------------ intelligence UI

function MembershipsPanel({ memberships }: { memberships: TriageMembership }) {
  return (
    <section className="flex flex-col gap-xs">
      <div className="flex items-center gap-sm">
        <Music4 className="size-[14px] text-text-muted" />
        <span className="micro-caps text-text-muted">
          Current memberships · {memberships.count}
        </span>
      </div>
      {memberships.count === 0 ? (
        <span className="text-sm text-text-secondary">
          Not in any owned playlist yet — a clean orphan.
        </span>
      ) : (
        <div className="flex flex-wrap gap-2xs">
          {memberships.playlist_names.map((name, i) => {
            const excluded = memberships.excluded[i] ?? false;
            return (
              <Badge
                key={memberships.playlist_ids[i] ?? name}
                variant={excluded ? "outline" : "secondary"}
                className={`rounded-sm ${excluded ? "text-text-muted" : ""}`}
              >
                {name || "Untitled"}
                {excluded && (
                  <span className="ml-2xs text-text-muted">· excluded</span>
                )}
              </Badge>
            );
          })}
        </div>
      )}
    </section>
  );
}

function SuggestionsPanel({
  suggestions,
  selectedIds,
  onToggle,
}: {
  suggestions: DestinationSuggestion[];
  selectedIds: number[];
  onToggle: (id: number) => void;
}) {
  const top = suggestions.slice(0, 8);
  return (
    <section className="flex flex-col gap-sm">
      <div className="flex items-center gap-sm">
        <Sparkles className="size-[14px] text-text-muted" />
        <Explain metric="suggestion_rank">
          <span className="micro-caps text-text-muted">
            Suggested destinations
          </span>
        </Explain>
      </div>
      {top.length === 0 ? (
        <span className="text-sm text-text-secondary">
          No confident destination — this song sits on its own.
        </span>
      ) : (
        <div className="flex flex-col gap-xs">
          {top.map((s) => (
            <SuggestionRow
              key={s.playlist_id}
              suggestion={s}
              selected={selectedIds.includes(s.playlist_id)}
              onToggle={() => onToggle(s.playlist_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SuggestionRow({
  suggestion,
  selected,
  onToggle,
}: {
  suggestion: DestinationSuggestion;
  selected: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const rows = evidenceRows(suggestion);

  return (
    <div
      className={`rounded-md border px-sm py-xs transition-colors ${
        selected
          ? "border-amber bg-surface-2"
          : "border-border-subtle bg-surface-1"
      }`}
    >
      <div className="flex items-center gap-sm">
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={selected}
          className={`flex size-[18px] shrink-0 items-center justify-center rounded-xs border transition-colors ${
            selected
              ? "border-amber bg-amber text-amber-ink"
              : "border-border-strong bg-surface-2 text-transparent hover:border-amber"
          }`}
          aria-label={`${selected ? "Deselect" : "Select"} ${suggestion.name}`}
        >
          <Check className="size-[12px]" strokeWidth={3} />
        </button>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex min-w-0 flex-1 items-center gap-sm text-left"
        >
          <span
            className={`truncate text-sm ${
              suggestion.already_in ? "text-text-muted" : "text-text-primary"
            }`}
          >
            {suggestion.name || "Untitled"}
          </span>
          {suggestion.already_in && (
            <Badge variant="outline" className="shrink-0 rounded-sm text-micro">
              ALREADY IN
            </Badge>
          )}
          <span className="data-readout ml-auto shrink-0 text-micro text-text-muted">
            {expanded ? "▴" : "▾"}
          </span>
        </button>
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="mt-sm flex flex-col gap-2xs pl-[26px]">
              {rows.map((row) => (
                <div
                  key={row.kind}
                  className="grid grid-cols-[120px_1fr] items-baseline gap-sm"
                >
                  <Explain metric={row.kind}>
                    <span className="micro-caps text-text-muted">
                      {row.label}
                    </span>
                  </Explain>
                  <span className="text-micro text-text-secondary">
                    {row.summary}
                  </span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NewCategoryPanel({
  newCategory,
  filedTrackId,
  draft,
  hasStrongFit,
  onSet,
}: {
  newCategory: NewCategory;
  filedTrackId: number;
  draft: { name: string; seedTrackIds: number[] } | null;
  hasStrongFit: boolean;
  onSet: (draft: { name: string; seedTrackIds: number[] } | null) => void;
}) {
  const proposal = newCategory.proposals[0];

  // Quiet states: below the clustering floor, still computing, or a strong
  // existing fit means a new playlist is rarely the answer.
  if (newCategory.status === "empty") {
    return (
      <QuietNewCategory note="Too few songs waiting to suggest a new playlist yet." />
    );
  }
  if (newCategory.status === "pending") {
    return (
      <QuietNewCategory note="Clustering the queue to suggest a new playlist…" />
    );
  }
  if (!proposal) {
    return <QuietNewCategory note="No distinct new cluster in the queue." />;
  }

  const active = draft !== null;
  const seed = proposal.founding_track_ids;

  return (
    <section
      className={`flex flex-col gap-sm rounded-md border p-md transition-opacity ${
        hasStrongFit && !active
          ? "border-border-subtle border-dashed opacity-60"
          : "border-border-subtle"
      }`}
    >
      <div className="flex items-center gap-sm">
        <Plus className="size-[14px] text-text-muted" />
        <Explain metric="cluster_proposal">
          <span className="micro-caps text-text-muted">New playlist</span>
        </Explain>
      </div>

      {active ? (
        <input
          value={draft.name}
          onChange={(e) => onSet({ name: e.target.value, seedTrackIds: seed })}
          className="data-readout rounded-sm border border-amber bg-surface-2 px-sm py-2xs text-sm text-text-primary outline-none"
          aria-label="New playlist name"
        />
      ) : (
        <span className="text-sm text-text-primary">
          {proposal.suggested_name}
        </span>
      )}

      <span className="text-micro text-text-secondary">
        Seed {seed.length} founding song{seed.length === 1 ? "" : "s"} from this
        cluster{seed.includes(filedTrackId) ? "" : ", plus this one"}.
      </span>

      <div className="flex items-center gap-sm">
        {active ? (
          <button
            type="button"
            onClick={() => onSet(null)}
            className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
          >
            CANCEL
          </button>
        ) : (
          <button
            type="button"
            onClick={() =>
              onSet({ name: proposal.suggested_name, seedTrackIds: seed })
            }
            className="micro-caps cursor-pointer rounded-sm border border-border-subtle px-md py-2xs text-text-secondary hover:text-text-primary"
          >
            CREATE + SEED
          </button>
        )}
        {active && (
          <span className="micro-caps text-text-muted">
            Applied with “File this song”
          </span>
        )}
      </div>
    </section>
  );
}

function QuietNewCategory({ note }: { note: string }) {
  return (
    <section className="flex items-center gap-sm rounded-md border border-border-subtle border-dashed px-md py-sm opacity-60">
      <Plus className="size-[13px] text-text-muted" />
      <span className="text-micro text-text-muted">{note}</span>
    </section>
  );
}

// ------------------------------------------------------------------- states

function OnboardingBanner() {
  return (
    <div className="flex flex-col gap-2xs rounded-md border border-border-subtle border-dashed bg-surface-1 px-md py-sm">
      <div className="flex items-center gap-sm">
        <Heart className="size-[13px] text-amber" />
        <span className="micro-caps text-text-muted">Triaging Liked Songs</span>
      </div>
      <span className="max-w-[52ch] text-micro text-text-secondary">
        No triage playlist set, so you're working your Liked Songs — oldest
        first. The ≤N slider hides songs already filed into playlists; at N=0
        you see only the orphans. Set a triage playlist above to work a specific
        inbox playlist instead.
      </span>
    </div>
  );
}

function QueueDrained({
  source,
  filtered,
}: {
  source: "liked" | "playlist";
  filtered: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center gap-sm py-2xl text-center"
    >
      <Check className="size-[28px] text-amber" strokeWidth={2.5} />
      <span className="display-caps text-sm text-text-primary">
        Queue clear
      </span>
      <span className="max-w-[40ch] text-micro text-text-secondary">
        {source === "liked"
          ? filtered
            ? "Every song in this filter has been triaged. Loosen the ≤N slider to widen the net."
            : "Every Liked Song has been triaged."
          : "This playlist has been triaged end to end."}
      </span>
    </motion.div>
  );
}

function PanelError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-xs rounded-md border border-danger/40 bg-surface-1 px-md py-sm">
      <span className="micro-caps text-danger">Something went wrong</span>
      <span className="text-sm text-text-secondary">{message}</span>
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

// -------------------------------------------------------------- skeletons

function SourceSkeleton() {
  return (
    <div className="flex flex-col gap-md">
      <Skeleton className="h-[38px] w-full" />
      <Skeleton className="h-[24px] w-2/3" />
    </div>
  );
}

function QueueSkeleton() {
  return (
    <div className="flex flex-col gap-md">
      <Skeleton className="h-[28px] w-1/2" />
      <Skeleton className="h-[36px] w-1/3" />
    </div>
  );
}

function IntelligenceSkeleton() {
  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-col gap-xs">
        <Skeleton className="h-[14px] w-1/3" />
        <Skeleton className="h-[24px] w-1/2" />
      </div>
      <div className="flex flex-col gap-xs">
        <Skeleton className="h-[14px] w-1/3" />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[34px] w-full" />
        ))}
      </div>
    </div>
  );
}
