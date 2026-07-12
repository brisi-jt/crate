/**
 * Edition-band state derivation — the field-journal header on the survey.
 *
 * Turns the editions collection into one of three honest display states:
 * no editions yet (prompt to compile), a baseline edition (edition 1, no
 * deltas — narrated as a first reading), or a delta edition (later, framed
 * as change). Pure logic — unit-tested.
 */

import type { Edition, EditionSummary } from "@/lib/api/schemas";

export type EditionBandState =
  | { kind: "empty" }
  | { kind: "baseline"; latest: EditionSummary }
  | { kind: "delta"; latest: EditionSummary };

/**
 * Classify the latest edition. Baseline vs delta keys off the edition number
 * (edition 1 is always the baseline reading, per the API's edition semantics).
 */
export function editionBandState(items: EditionSummary[]): EditionBandState {
  if (items.length === 0) return { kind: "empty" };
  // The list is newest-first; the highest edition_number is the current one.
  const latest = items.reduce((a, b) =>
    b.edition_number > a.edition_number ? b : a,
  );
  return latest.edition_number <= 1
    ? { kind: "baseline", latest }
    : { kind: "delta", latest };
}

/** Narrative kind → semantic tint token (a CSS variable / utility hue). */
export type NarrativeTint = "amber" | "sage" | "rose" | "neutral";

const KIND_TINT: Record<string, NarrativeTint> = {
  baseline: "neutral",
  steady: "neutral",
  entropy: "amber",
  sprawl: "amber",
  rarity: "rose",
  archetype: "amber",
  dormancy: "rose",
  fingerprint: "sage",
};

export function narrativeTint(kind: string): NarrativeTint {
  return KIND_TINT[kind] ?? "neutral";
}

/** "EDITION 3 · WEEK OF 06 JUL 2026" from an edition/summary. */
export function editionLabel(edition: Edition | EditionSummary): string {
  return `EDITION ${edition.edition_number} · ${formatWeek(edition.week_start)}`;
}

/** ISO datetime → "WEEK OF 06 JUL 2026". */
export function formatWeek(iso: string): string {
  const date = new Date(
    iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`,
  );
  if (Number.isNaN(date.getTime())) return "WEEK OF —";
  const months = [
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
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `WEEK OF ${day} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}
