import type { RadioItem, RadioSummary } from "@/lib/api/schemas";

/**
 * Next item with playable audio at or after `from` (wraps nothing — a radio
 * run moves forward only). Returns null when the rest of the session is
 * preview-less.
 */
export function nextPlayableIndex(
  items: RadioItem[],
  from: number,
): number | null {
  for (let index = Math.max(0, from); index < items.length; index += 1) {
    if (items[index].preview_url) return index;
  }
  return null;
}

/** Progress rollup recomputed client-side after optimistic item updates. */
export function sessionSummary(items: RadioItem[]): RadioSummary {
  const kept = items.filter((item) => item.feedback === "kept").length;
  const skipped = items.filter((item) => item.feedback === "skipped").length;
  const added = items.filter((item) => item.journal_id !== null).length;
  return { kept, skipped, added, pending: items.length - kept - skipped };
}

/** Every item has a verdict — time for the session summary. */
export function sessionComplete(items: RadioItem[]): boolean {
  return items.length > 0 && items.every((item) => item.feedback !== null);
}

/** Transition readout for a tracklist row: "128 BPM · 8A" parts when known. */
export function itemReadout(item: RadioItem): string | null {
  const parts: string[] = [];
  if (item.tempo !== null) parts.push(`${Math.round(item.tempo)} BPM`);
  if (item.camelot !== null) parts.push(item.camelot);
  return parts.length > 0 ? parts.join(" · ") : null;
}
