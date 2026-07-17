/**
 * Pure view-model helpers for the extended-survey sections. Formatting and
 * ordering logic lives here (unit-tested); the section components stay thin.
 */

import type {
  ExtendedCoverage,
  PlayMoodByHour,
} from "@/lib/api/schemas-extended";

/** A rate in [0,1] as a whole-number percent; an em dash when null. */
export function formatRate(rate: number | null): string {
  if (rate === null) return "—";
  return `${Math.round(rate * 100)}%`;
}

/** An hour-of-day as a 24h clock label; an em dash when null. */
export function formatClock(hour: number | null): string {
  if (hour === null) return "—";
  return `${String(hour).padStart(2, "0")}:00`;
}

const BAND_ORDER = ["morning", "afternoon", "evening", "night"];

/** Order the time-of-day mood bands morning → night; unknowns trail. */
export function orderMoodBands(
  bands: PlayMoodByHour["bands"],
): PlayMoodByHour["bands"] {
  const rank = (band: string) => {
    const i = BAND_ORDER.indexOf(band);
    return i === -1 ? BAND_ORDER.length : i;
  };
  return [...bands].sort((a, b) => rank(a.band) - rank(b.band));
}

/** Contexts sorted by share, biggest first. */
export function topContexts<T extends { share: number }>(contexts: T[]): T[] {
  return [...contexts].sort((a, b) => b.share - a.share);
}

/**
 * Whether the library carries listening history from before crate started —
 * i.e. an imported streaming export extends the play record into the past. When
 * false, every play is a since-crate play and there's nothing to distinguish.
 */
export function hasPlayHistory(coverage: ExtendedCoverage): boolean {
  return coverage.play_events > coverage.since_crate_plays;
}

/** A section whose driving total is zero has nothing to show yet. */
export function isExtendedSectionEmpty(total: number): boolean {
  return total <= 0;
}
