"use client";

import { useMemo, useState } from "react";
import { FieldGuideCard } from "@/components/chrome/field-guide-card";
import { Explain, ExplainReadout } from "@/components/explain/explain";
import { TargetPicker } from "@/components/panels/target-picker";
import { Separator } from "@/components/ui/separator";
import { useFrontier, useSeedDiscovery } from "@/hooks/api/use-frontier";
import { usePlaylists } from "@/hooks/api/use-playlists";
import type { DiscoveryRunResult, FrontierGenre } from "@/lib/api/schemas";
import { openListeningDeck } from "@/lib/store/deck";

const TERRITORY_SHOWN = 12;

/**
 * The frontier explorer: where the library lives in genre space and what
 * borders it. Territory reads as a ranked constellation list (presence bars
 * are neutral — genre standing is structure, not sound); each frontier
 * genre expands to its exemplar artists and a seed action that targets a
 * discovery pass at a chosen playlist.
 */
export function FrontierPanelContent() {
  const frontier = useFrontier();
  const playlists = usePlaylists();
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const targets = useMemo(
    () =>
      playlists.data?.items
        .filter((p) => !p.is_deleted && p.is_owned)
        .map((p) => ({ id: p.id, name: p.name })) ?? [],
    [playlists.data],
  );

  if (frontier.isPending) {
    return (
      <span className="micro-caps text-text-muted">
        SURVEYING GENRE SPACE · FIRST PASS READS THE FULL ATLAS
      </span>
    );
  }

  if (frontier.isError || !frontier.data) {
    return (
      <div className="flex flex-col items-start gap-xs">
        <span className="micro-caps text-danger">FRONTIER UNAVAILABLE</span>
        <button
          type="button"
          onClick={() => frontier.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  const { territory, frontier: frontierGenres, coverage } = frontier.data;

  if (territory.length === 0) {
    return (
      <div className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">NO TERRITORY YET</span>
        <p className="max-w-[52ch] text-sm text-text-secondary">
          The frontier maps your artists onto the genre atlas. It needs a synced
          library — and the atlas import — before there's territory to chart.
          Sync, then come back.
        </p>
      </div>
    );
  }

  return (
    <>
      <FieldGuideCard
        mode="frontier"
        variant="inline"
        stats={{
          territoryCount: territory.length,
          frontierCount: frontierGenres.length,
        }}
      />

      <div className="flex gap-xl">
        <ExplainReadout
          metric="territory"
          label="Territory"
          value={`${territory.length} GENRES`}
        />
        <ExplainReadout
          metric="frontier"
          label="Frontier"
          value={String(frontierGenres.length)}
        />
        <ExplainReadout
          metric="matched_artists"
          label="Atlas match"
          value={`${coverage.matched_artists}/${coverage.library_artists} ARTISTS`}
        />
      </div>

      <Separator />

      <section className="flex flex-col gap-xs">
        <Explain metric="presence">
          <span className="micro-caps text-text-muted">
            Territory — strongest first
          </span>
        </Explain>
        <div className="flex flex-col gap-2xs">
          {territory.slice(0, TERRITORY_SHOWN).map((genre, index) => (
            <div key={genre.genre_id} className="flex items-center gap-sm">
              <span className="data-readout w-[24px] text-micro text-text-muted">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="w-[180px] truncate text-sm text-text-primary">
                {genre.name}
              </span>
              <div className="h-[4px] flex-1 rounded-xs bg-surface-2">
                <div
                  className="h-full rounded-xs bg-border-strong"
                  style={{ width: `${Math.max(2, genre.presence * 100)}%` }}
                />
              </div>
              <span className="data-readout w-[64px] text-right text-micro text-text-muted">
                {genre.matched_artists} ART
              </span>
            </div>
          ))}
        </div>
        {territory.length > TERRITORY_SHOWN && (
          <span className="data-readout text-micro text-text-muted">
            +{territory.length - TERRITORY_SHOWN} MORE GENRES HELD
          </span>
        )}
      </section>

      <Separator />

      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">
          Frontier — adjacent, unexplored
        </span>
        {frontierGenres.length === 0 ? (
          <p className="max-w-[52ch] text-sm text-text-secondary">
            Nothing borders the territory yet — frontier genres appear once the
            atlas finds neighbors your library barely holds.
          </p>
        ) : (
          <div className="flex flex-col">
            {frontierGenres.map((genre) => (
              <FrontierGenreRow
                key={genre.genre_id}
                genre={genre}
                expanded={expandedId === genre.genre_id}
                onToggle={() =>
                  setExpandedId((prev) =>
                    prev === genre.genre_id ? null : genre.genre_id,
                  )
                }
                targets={targets}
              />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function FrontierGenreRow({
  genre,
  expanded,
  onToggle,
  targets,
}: {
  genre: FrontierGenre;
  expanded: boolean;
  onToggle: () => void;
  targets: Array<{ id: number; name: string }>;
}) {
  const seed = useSeedDiscovery();
  const [targetId, setTargetId] = useState<number | null>(null);
  const [result, setResult] = useState<DiscoveryRunResult | null>(null);

  return (
    <div className="flex flex-col border-border-subtle border-b py-xs last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex cursor-pointer items-center gap-sm rounded-xs px-2xs py-2xs text-left hover:bg-surface-2"
      >
        <span className="data-readout w-[44px] text-micro text-text-muted">
          {genre.score.toFixed(2)}
        </span>
        <span className="truncate font-bold text-sm text-text-primary">
          {genre.name}
        </span>
        <span className="truncate text-micro text-text-muted">
          {genre.adjacent_to.length > 0 &&
            `borders ${genre.adjacent_to.join(" · ")}`}
        </span>
        <span className="data-readout ml-auto text-micro text-text-muted">
          {expanded ? "−" : "+"}
        </span>
      </button>

      {expanded && (
        <div className="flex flex-col gap-sm px-2xs pt-xs pb-2xs">
          <div className="flex flex-col gap-2xs">
            {genre.exemplars.map((exemplar) => (
              <div key={exemplar.name} className="flex items-center gap-sm">
                <span className="w-[200px] truncate text-sm text-text-primary">
                  {exemplar.name}
                </span>
                <div className="h-[4px] flex-1 rounded-xs bg-surface-2">
                  <div
                    className="h-full rounded-xs bg-border-strong"
                    style={{ width: `${Math.max(2, exemplar.weight * 100)}%` }}
                  />
                </div>
                <span className="data-readout w-[40px] text-right text-micro text-text-muted">
                  {exemplar.weight.toFixed(2)}
                </span>
              </div>
            ))}
            {genre.exemplars.length === 0 && (
              <span className="text-sm text-text-secondary">
                Every defining artist of this genre is already in the library.
              </span>
            )}
          </div>

          {genre.exemplars.length > 0 && (
            <div className="flex items-center gap-sm">
              <TargetPicker
                options={targets}
                value={targetId}
                onPick={setTargetId}
              />
              <button
                type="button"
                disabled={targetId === null || seed.isPending}
                onClick={() => {
                  if (targetId === null) return;
                  setResult(null);
                  seed.mutate(
                    { playlistId: targetId, genre: genre.name },
                    { onSuccess: setResult },
                  );
                }}
                className="display-caps cursor-pointer rounded-sm bg-amber px-md py-2xs text-amber-ink text-micro transition-colors duration-150 hover:bg-amber-press disabled:cursor-default disabled:opacity-45"
              >
                {seed.isPending ? "Seeding…" : "Seed discovery"}
              </button>
            </div>
          )}

          {seed.isPending && (
            <span className="micro-caps text-text-muted">
              SEEDING FROM {genre.name.toUpperCase()} · GENERATE → RESOLVE →
              PREVIEW
            </span>
          )}
          {seed.isError && (
            <span className="micro-caps text-danger">
              SEED PASS FAILED · TRY AGAIN
            </span>
          )}
          {result && (
            <div className="flex items-center gap-md">
              <span className="data-readout text-micro text-text-secondary">
                GENERATED {result.generated_enao ?? 0} · RESOLVED{" "}
                {result.resolved} · PREVIEWS {result.previews_resolved}
              </span>
              {targetId !== null && (
                <button
                  type="button"
                  onClick={() => openListeningDeck(targetId)}
                  className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
                >
                  OPEN DECK
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
