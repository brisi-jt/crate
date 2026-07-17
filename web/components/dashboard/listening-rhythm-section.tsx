"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import { NameLine } from "@/components/insights/extended/extended-kit";
import { ShareButton } from "@/components/share/share-button";
import type {
  ListeningDashboard,
  ListeningRange,
} from "@/lib/api/schemas-competitive";
import {
  clockBars,
  formatMinutes,
  weekdayBars,
} from "@/lib/competitive/dashboard-view";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ClockRow({ data }: { data: ListeningDashboard }) {
  const bars = clockBars(data.clock.hours, data.clock.peak_hour);
  const peakLabel =
    data.clock.peak_hour !== null
      ? `${String(data.clock.peak_hour).padStart(2, "0")}:00`
      : "—";
  return (
    <div className="flex flex-col gap-xs">
      <div className="flex items-baseline justify-between gap-sm">
        <Explain metric="listening_clock">
          <span className="micro-caps text-text-muted">
            Listening clock — hour of day
          </span>
        </Explain>
        <Explain metric="listening_clock_peak">
          <span className="data-readout text-micro text-text-muted">
            peak {peakLabel}
          </span>
        </Explain>
      </div>
      <div className="flex items-end gap-[2px]" aria-hidden>
        {bars.map((bar) => (
          <div
            key={bar.index}
            title={`${String(bar.index).padStart(2, "0")}:00 · ${bar.count} plays`}
            className="flex-1 rounded-xs bg-border-strong"
            style={{
              height: `${Math.max(2, bar.fraction * 48)}px`,
              opacity: bar.peak ? 1 : 0.55,
            }}
          />
        ))}
      </div>
    </div>
  );
}

function WeekdayRow({ data }: { data: ListeningDashboard }) {
  const bars = weekdayBars(data.clock.weekdays);
  return (
    <div className="flex flex-col gap-xs">
      <span className="micro-caps text-text-muted">By day of week</span>
      <div className="flex items-end gap-xs" aria-hidden>
        {bars.map((bar, i) => (
          <div
            key={bar.label}
            className="flex flex-1 flex-col items-center gap-2xs"
          >
            <div className="flex h-[48px] w-full items-end">
              <div
                className="w-full rounded-xs bg-border-strong"
                style={{ height: `${Math.max(3, bar.fraction * 48)}px` }}
              />
            </div>
            <span className="data-readout text-micro text-text-muted">
              {WEEKDAY_LABELS[i]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ListeningRhythmSection({
  data,
  range,
  onRangeChange,
  showRangeToggle,
}: {
  data: ListeningDashboard;
  range: ListeningRange;
  onRangeChange: (range: ListeningRange) => void;
  showRangeToggle: boolean;
}) {
  if (data.total_plays === 0) {
    return (
      <p className="max-w-[56ch] text-sm text-text-secondary">
        No plays recorded in this range yet. As listening accrues — or once you
        import your streaming history — your rhythm fills in here.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-lg">
      {/* Range toggle — only when imported history makes the two ranges differ. */}
      {showRangeToggle && (
        <div className="flex items-center gap-xs">
          {(["all_time", "since_crate"] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => onRangeChange(r)}
              aria-pressed={range === r}
              className={`micro-caps cursor-pointer rounded-xs border px-sm py-2xs ${
                range === r
                  ? "border-amber text-amber"
                  : "border-border-subtle text-text-muted hover:text-text-secondary"
              }`}
            >
              {r === "all_time" ? "All time" : "Since crate"}
            </button>
          ))}
        </div>
      )}

      {/* Headline scalars */}
      <div className="flex flex-wrap items-end gap-xl">
        <ExplainReadout
          metric="listening_rhythm"
          label="Plays"
          value={data.total_plays.toLocaleString()}
        />
        <ExplainReadout
          metric="listening_rhythm"
          label="Tracks"
          value={data.distinct_tracks.toLocaleString()}
        />
        <ExplainReadout
          metric="listening_minutes"
          label="Listened"
          value={formatMinutes(data.minutes)}
        />
        <ExplainReadout
          metric="listening_streaks"
          label="Longest streak"
          value={`${data.streaks.longest}d`}
        />
        <div className="ml-auto">
          <ShareButton
            kind="listening"
            title="Listening rhythm"
            subtitle={range === "all_time" ? "all time" : "since crate"}
          >
            <div className="flex flex-col gap-[40px]">
              <div className="flex justify-center gap-[64px] text-center">
                <div className="flex flex-col gap-[6px]">
                  <span className="micro-caps text-[15px] text-text-muted">
                    Plays
                  </span>
                  <span className="data-readout text-[52px] text-text-primary">
                    {data.total_plays.toLocaleString()}
                  </span>
                </div>
                <div className="flex flex-col gap-[6px]">
                  <span className="micro-caps text-[15px] text-text-muted">
                    Minutes
                  </span>
                  <span className="data-readout text-[52px] text-text-primary">
                    {Math.round(data.minutes.minutes).toLocaleString()}
                  </span>
                </div>
                <div className="flex flex-col gap-[6px]">
                  <span className="micro-caps text-[15px] text-text-muted">
                    Streak
                  </span>
                  <span className="data-readout text-[52px] text-text-primary">
                    {data.streaks.longest}d
                  </span>
                </div>
              </div>
              <ClockRow data={data} />
            </div>
          </ShareButton>
        </div>
      </div>

      <ClockRow data={data} />
      <WeekdayRow data={data} />

      {/* Most-played */}
      {data.top_played.length > 0 && (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">Most played</span>
          <div className="flex flex-col gap-2xs">
            {data.top_played.slice(0, 8).map((t) => (
              <NameLine
                key={t.track_id}
                title={t.name}
                subtitle={t.artist}
                trailing={`${t.plays} plays`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
