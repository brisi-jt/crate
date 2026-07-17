import type {
  DestinationSuggestion,
  Evidence,
  EvidenceKind,
} from "@/lib/api/schemas";

/**
 * The evidence view-model: one labeled row per named signal, in a fixed
 * canonical order, carrying its OWN strength — never a blended score. The
 * spec is explicit that a suggestion shows four separately-labeled signals,
 * so the assembly here refuses to collapse them into one number.
 */

/** Canonical render order — strongest-signal-first is a UI choice, not this. */
const ORDER: EvidenceKind[] = [
  "sonic_fit",
  "artist_overlap",
  "placement_history",
  "vibe_match",
];

export const EVIDENCE_LABELS: Record<EvidenceKind, string> = {
  sonic_fit: "Sonic fit",
  artist_overlap: "Artist overlap",
  placement_history: "Placement history",
  vibe_match: "Name / vibe match",
};

export interface EvidenceRow {
  kind: EvidenceKind;
  label: string;
  summary: string;
  /** Per-signal strength 0–1, for the row's bar fill. */
  strength: number;
  detail: Record<string, unknown>;
}

function rankOf(kind: EvidenceKind): number {
  const i = ORDER.indexOf(kind);
  return i < 0 ? ORDER.length : i;
}

export function evidenceRows(suggestion: DestinationSuggestion): EvidenceRow[] {
  const known = new Set<EvidenceKind>(ORDER);
  return suggestion.evidence
    .filter((e: Evidence) => known.has(e.kind))
    .slice()
    .sort((a, b) => rankOf(a.kind) - rankOf(b.kind))
    .map((e) => ({
      kind: e.kind,
      label: EVIDENCE_LABELS[e.kind],
      summary: e.summary,
      strength: e.score,
      detail: e.detail ?? {},
    }));
}
