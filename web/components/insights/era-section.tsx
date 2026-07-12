"use client";

import { useEffect, useState } from "react";
import { Readout } from "@/components/panels/right-dock";
import { useSetBirthYear } from "@/hooks/api/use-me";
import type { Eras } from "@/lib/api/schemas";

interface EraSectionProps {
  eras: Eras;
  birthYear: number | null;
}

/**
 * ERA — decade strip with the taste-freeze reading. Decades render as
 * calibrated bands (height = share). When a birth year is set, the 16–24
 * coming-of-age window overlays as a faint band. An inline SET BIRTH YEAR
 * input writes PATCH /v1/me and the survey recomputes the overlay.
 */
export function EraSection({ eras, birthYear }: EraSectionProps) {
  const { decades, center_of_gravity, median_year, coming_of_age, total } =
    eras;
  const maxCount = decades.reduce((m, d) => Math.max(m, d.count), 0);

  if (total === 0) {
    return (
      <div className="flex flex-col gap-sm">
        <p className="max-w-[56ch] text-sm text-text-secondary">
          Release years are still filling in. The era strip charts your library
          by decade once tracks carry dated albums.
        </p>
        <BirthYearInput birthYear={birthYear} />
      </div>
    );
  }

  const width = 380;
  const barGap = 4;
  const barW = (width - barGap * (decades.length - 1)) / decades.length;
  const plotH = 96;
  const minDecade = decades[0]?.decade ?? 0;
  const decadeSpan =
    (decades[decades.length - 1]?.decade ?? minDecade) - minDecade || 1;

  // coming-of-age overlay position: map its year window onto the decade axis
  const bandRect = coming_of_age
    ? (() => {
        const startX =
          ((coming_of_age.band_start_year - minDecade) / (decadeSpan + 10)) *
          width;
        const endX =
          ((coming_of_age.band_end_year - minDecade) / (decadeSpan + 10)) *
          width;
        return {
          x: Math.max(0, startX),
          w: Math.max(4, Math.min(width, endX) - Math.max(0, startX)),
        };
      })()
    : null;

  return (
    <div className="flex flex-col gap-md">
      <div className="flex flex-wrap gap-lg">
        <Readout
          label="Center of gravity"
          value={center_of_gravity !== null ? String(center_of_gravity) : "—"}
        />
        <Readout
          label="Median year"
          value={median_year !== null ? String(median_year) : "—"}
        />
        <Readout label="Dated tracks" value={total.toLocaleString()} />
      </div>

      <svg
        width={width}
        height={plotH + 18}
        viewBox={`0 0 ${width} ${plotH + 18}`}
        role="img"
        aria-label="Release era strip"
      >
        <title>Library distribution by decade of release</title>
        {/* coming-of-age band behind the bars */}
        {bandRect && (
          <rect
            x={bandRect.x}
            y={0}
            width={bandRect.w}
            height={plotH}
            fill="var(--accent-amber)"
            fillOpacity={0.12}
          />
        )}
        {decades.map((d, i) => {
          const h = maxCount > 0 ? (d.count / maxCount) * plotH : 0;
          const x = i * (barW + barGap);
          return (
            <g key={d.decade}>
              <rect
                x={x}
                y={plotH - h}
                width={barW}
                height={h}
                rx={1}
                fill="var(--border-strong)"
                fillOpacity={0.65}
              />
              <text
                x={x + barW / 2}
                y={plotH + 12}
                textAnchor="middle"
                className="data-readout"
                fontSize={8.5}
                fill="var(--text-muted)"
              >
                {`${String(d.decade).slice(2)}s`}
              </text>
            </g>
          );
        })}
      </svg>

      {coming_of_age && (
        <p className="max-w-[56ch] text-sm text-text-secondary">
          Your coming-of-age window ({coming_of_age.band_start_year}–
          {coming_of_age.band_end_year}) holds{" "}
          <span className="data-readout text-text-primary">
            {(coming_of_age.share * 100).toFixed(0)}%
          </span>{" "}
          of your dated library — {coming_of_age.count.toLocaleString()} tracks.
        </p>
      )}

      <BirthYearInput birthYear={birthYear} />
    </div>
  );
}

function BirthYearInput({ birthYear }: { birthYear: number | null }) {
  const setBirthYear = useSetBirthYear();
  const [value, setValue] = useState(
    birthYear !== null ? String(birthYear) : "",
  );
  const [error, setError] = useState<string | null>(null);

  // Keep local input aligned when the server value changes (e.g. from clear).
  useEffect(() => {
    setValue(birthYear !== null ? String(birthYear) : "");
  }, [birthYear]);

  const currentYear = new Date().getFullYear();

  function submit() {
    setError(null);
    const trimmed = value.trim();
    if (trimmed === "") {
      setBirthYear.mutate(null);
      return;
    }
    const year = Number.parseInt(trimmed, 10);
    if (Number.isNaN(year) || year < 1900 || year > currentYear - 13) {
      setError(`Enter a year between 1900 and ${currentYear - 13}.`);
      return;
    }
    setBirthYear.mutate(year, {
      onError: () => setError("Could not save — try again."),
    });
  }

  return (
    <div className="flex flex-col gap-2xs">
      <span className="micro-caps text-text-muted">
        Birth year — draws your 16–24 window
      </span>
      <div className="flex items-center gap-sm">
        <input
          type="text"
          inputMode="numeric"
          value={value}
          placeholder="e.g. 1992"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          className="data-readout w-[92px] rounded-sm border border-border bg-surface-2 px-sm py-2xs text-sm text-text-primary outline-none focus:border-amber"
        />
        <button
          type="button"
          onClick={submit}
          disabled={setBirthYear.isPending}
          className="micro-caps cursor-pointer text-text-secondary hover:text-text-primary disabled:text-text-muted"
        >
          {setBirthYear.isPending
            ? "SAVING…"
            : birthYear !== null
              ? "UPDATE"
              : "SET"}
        </button>
        {birthYear !== null && (
          <button
            type="button"
            onClick={() => {
              setValue("");
              setBirthYear.mutate(null);
            }}
            className="micro-caps cursor-pointer text-text-muted hover:text-danger"
          >
            CLEAR
          </button>
        )}
      </div>
      {error && <span className="micro-caps text-danger">{error}</span>}
    </div>
  );
}
