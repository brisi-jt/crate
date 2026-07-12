/**
 * Core-sample strip geometry — the adds-over-time reading as a geological core.
 *
 * Each month is a thin sediment band; its color is the acoustic centroid of
 * what was added that month (grey when nothing enriched). Band height encodes
 * add count on a sqrt scale so a huge month doesn't flatten quiet ones.
 * Pure math + color so bucketing→tint is unit-tested.
 */

import type { AddsOverTime } from "@/lib/api/schemas";
import {
  acousticColor,
  GREY_NODE,
  type Oklch,
  oklchString,
} from "@/lib/color/acoustic";

export interface CoreBand {
  month: string;
  count: number;
  /** OKLCH tint from the month's centroid; grey when unenriched. */
  color: Oklch;
  colorString: string;
  /** 0..1 fill share of the max-count month (sqrt-scaled for legibility). */
  intensity: number;
  /** True when the month has adds but none enriched (grey, honest). */
  unenriched: boolean;
}

/**
 * Turn adds-over-time buckets into colored bands. `intensity` is
 * `sqrt(count / maxCount)` so relative volume reads without a tall month
 * crushing the rest to invisible slivers.
 */
export function coreBands(adds: AddsOverTime[]): CoreBand[] {
  const maxCount = adds.reduce((m, a) => Math.max(m, a.count), 0);
  return adds.map((a) => {
    const color = a.centroid ? acousticColor(a.centroid) : GREY_NODE;
    const intensity = maxCount > 0 ? Math.sqrt(a.count / maxCount) : 0;
    return {
      month: a.month,
      count: a.count,
      color,
      colorString: oklchString(color),
      intensity,
      unenriched: a.count > 0 && a.centroid === null,
    };
  });
}

/** "2024-01" → "JAN '24" for sparse axis labels. */
export function formatCoreMonth(month: string): string {
  const [year, mon] = month.split("-");
  const names = [
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
  ];
  const idx = Number.parseInt(mon ?? "1", 10) - 1;
  const name = names[idx] ?? mon ?? "";
  return `${name} '${(year ?? "").slice(2)}`;
}

/**
 * Pick roughly `count` evenly-spaced band indices for axis ticks — first,
 * last, and interior points — so a long core sample gets a legible axis
 * without labeling every month.
 */
export function axisTickIndices(total: number, count: number): number[] {
  if (total <= count) return Array.from({ length: total }, (_, i) => i);
  const step = (total - 1) / (count - 1);
  const out = new Set<number>();
  for (let i = 0; i < count; i++) out.add(Math.round(i * step));
  return [...out].sort((a, b) => a - b);
}
