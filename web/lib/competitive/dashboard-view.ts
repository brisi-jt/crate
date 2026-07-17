/**
 * Pure view-model helpers for the listening dashboard (F1), obscurity (F3),
 * taste drift (F5), and quality (F6) surfaces. Components stay thin; every bit
 * of formatting/ordering/gating lives and is tested here.
 */

import type { DriftAxis, ListeningRange } from "@/lib/api/schemas-competitive";

// ── F1 range toggle ──────────────────────────────────────────────────────────

export function rangeParam(range: ListeningRange): string {
  return range;
}

export function nextRange(range: ListeningRange): ListeningRange {
  return range === "all_time" ? "since_crate" : "all_time";
}

/**
 * The all-time / since-crate toggle only makes sense once imported history
 * extends the play record past crate's own captures. With no imports every play
 * is a since-crate play, so the two ranges are identical — hide the toggle.
 */
export function hasImportedHistory({
  totalPlays,
  sinceCratePlays,
}: {
  totalPlays: number;
  sinceCratePlays: number;
}): boolean {
  return totalPlays > sinceCratePlays;
}

// ── minutes ──────────────────────────────────────────────────────────────────

export function formatMinutes({
  minutes,
  estimated,
}: {
  minutes: number;
  estimated: boolean;
}): string {
  const total = Math.round(minutes);
  const body =
    total < 60 ? `${total} min` : `${Math.floor(total / 60)}h ${total % 60}m`;
  return estimated ? `${body} (est)` : body;
}

// ── clock + weekday bars ─────────────────────────────────────────────────────

export interface ClockBar {
  index: number;
  count: number;
  fraction: number;
  peak: boolean;
}

export function clockBars(
  hours: number[],
  peakHour: number | null,
): ClockBar[] {
  const max = Math.max(0, ...hours);
  return hours.map((count, index) => ({
    index,
    count,
    fraction: max > 0 ? count / max : 0,
    peak: peakHour !== null && index === peakHour,
  }));
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export interface WeekdayBar {
  label: string;
  count: number;
  fraction: number;
}

export function weekdayBars(weekdays: number[]): WeekdayBar[] {
  const max = Math.max(0, ...weekdays);
  return weekdays.map((count, i) => ({
    label: WEEKDAYS[i] ?? `D${i}`,
    count,
    fraction: max > 0 ? count / max : 0,
  }));
}

// ── F3 obscurity ─────────────────────────────────────────────────────────────

export function formatObscurity(score: number | null): string {
  if (score === null) return "—";
  return `${Math.round(score * 100)}%`;
}

/** A one-word niche/mainstream lean for a 0..1 obscurity score. */
export function obscurityLean(score: number | null): string {
  if (score === null) return "unscored";
  if (score >= 0.66) return "deep-cut";
  if (score <= 0.33) return "mainstream";
  return "mixed";
}

// ── F5 drift ─────────────────────────────────────────────────────────────────

export function driftAxesSorted(axes: DriftAxis[]): DriftAxis[] {
  return [...axes].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}

// ── F6 quality ───────────────────────────────────────────────────────────────

export function qualitySubscorePercent(value: number): number {
  return Math.round(value * 100);
}
