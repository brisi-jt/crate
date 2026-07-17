"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import {
  BarRow,
  ExtendedEmpty,
  NameLine,
} from "@/components/insights/extended/extended-kit";
import type { PlayEventsSection } from "@/lib/api/schemas-extended";
import {
  formatClock,
  formatRate,
  orderMoodBands,
  topContexts,
} from "@/lib/insights/extended-view";

/**
 * LISTENING — the true implicit signal. Everything here reads from play history
 * (which the streaming-history import extends into the past): what you play vs
 * what you file, when you listen, how fresh your rotation is, and where plays
 * come from.
 */
export function PlayHistorySection({
  play,
  totalPlays,
}: {
  play: PlayEventsSection;
  totalPlays: number;
}) {
  if (totalPlays === 0) {
    return (
      <ExtendedEmpty note="No plays recorded yet. Once listening history accrues — or you import your streaming history — your clock, rotation, and play-vs-collect gaps fill in here." />
    );
  }

  const { play_collect_gap, listening_clock, rotation_velocity, context_mix } =
    play;
  const clockMax = Math.max(1, ...listening_clock.hours);
  const clockBars = listening_clock.hours.map((count, hour) => ({
    label: formatClock(hour),
    hour,
    count,
  }));
  const contexts = topContexts(context_mix.contexts);
  const bands = orderMoodBands(play.play_mood_by_hour.bands);

  return (
    <div className="flex flex-col gap-lg">
      {/* Listening clock */}
      <div className="flex flex-col gap-xs">
        <div className="flex items-baseline justify-between gap-sm">
          <Explain metric="listening_clock">
            <span className="micro-caps text-text-muted">
              Listening clock — hour of day
            </span>
          </Explain>
          <span className="data-readout text-micro text-text-muted">
            peak {formatClock(listening_clock.peak_hour)}
          </span>
        </div>
        <div className="flex items-end gap-[2px]" aria-hidden>
          {clockBars.map((bar) => (
            <div
              key={bar.label}
              title={`${bar.label} · ${bar.count} plays`}
              className="flex-1 rounded-xs bg-border-strong"
              style={{
                height: `${Math.max(2, (bar.count / clockMax) * 48)}px`,
                opacity: bar.hour === listening_clock.peak_hour ? 1 : 0.55,
              }}
            />
          ))}
        </div>
      </div>

      {/* Scalars */}
      <div className="flex flex-wrap gap-lg">
        <ExplainReadout
          metric="rotation_velocity"
          label="Rotation velocity"
          value={formatRate(rotation_velocity.recency_bias)}
        />
        <ExplainReadout
          metric="deep_cuts_vs_hits"
          label="Deep-cut share"
          value={formatRate(play.deep_cuts_vs_hits.deep_cut_share)}
        />
      </div>

      {/* Context mix */}
      {contexts.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="context_mix">
            <span className="micro-caps text-text-muted">Play context</span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {contexts.map((c) => (
              <BarRow
                key={c.context}
                label={c.context}
                fraction={c.share}
                value={`${(c.share * 100).toFixed(0)}%`}
              />
            ))}
          </div>
        </div>
      )}

      {/* Mood by time of day */}
      {bands.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="play_mood_by_hour">
            <span className="micro-caps text-text-muted">
              Mood by time of day
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {bands.map((b) => (
              <div key={b.band} className="flex items-center gap-sm">
                <span className="w-[96px] text-sm text-text-secondary capitalize">
                  {b.band}
                </span>
                <span className="data-readout text-micro text-text-muted">
                  energy {(b.mean_energy * 100).toFixed(0)} · mood{" "}
                  {(b.mean_valence * 100).toFixed(0)} · {b.count} plays
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Play vs collect gap */}
      {play_collect_gap.over_played.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="play_collect_gap">
            <span className="micro-caps text-text-muted">
              You play more than you've filed
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {play_collect_gap.over_played.slice(0, 6).map((t) => (
              <NameLine
                key={t.track_id}
                title={t.name}
                subtitle={t.artist}
                trailing={`${t.plays} plays · ${t.memberships} pl`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
