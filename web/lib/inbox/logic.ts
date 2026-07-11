import type {
  DigestItem,
  DigestSection,
  DigestSummary,
} from "@/lib/api/schemas";

/** Fixed reading order for digest sections. */
export const SECTION_ORDER: DigestSection[] = [
  "suggestions",
  "candidates",
  "library",
  "listening",
  "frontier",
];

export const SECTION_TITLES: Record<DigestSection, string> = {
  suggestions: "New suggestions",
  candidates: "Top of the queues",
  library: "Library changes",
  listening: "Listening",
  frontier: "Frontier",
};

/** True when any digest has never been opened — drives the chrome marker. */
export function hasUnread(digests: Pick<DigestSummary, "read_at">[]): boolean {
  return digests.some((digest) => digest.read_at === null);
}

/** Group a digest's items into sections, reading order preserved. */
export function groupBySection(
  items: DigestItem[],
): Array<{ section: DigestSection; items: DigestItem[] }> {
  return SECTION_ORDER.map((section) => ({
    section,
    items: items.filter((item) => item.section === section),
  })).filter((group) => group.items.length > 0);
}

export type DeepLink =
  | { kind: "deck"; playlistId: number }
  | { kind: "playlist"; playlistId: number }
  | { kind: "frontier"; genre: string };

/**
 * Where an item jumps: suggestion/candidate items open the deck on their
 * playlist, library items select the playlist on the map, frontier items
 * open the frontier explorer. Listening notes are readouts — no link.
 */
export function deepLinkFor(item: DigestItem): DeepLink | null {
  if (
    (item.section === "suggestions" || item.section === "candidates") &&
    item.playlist_id !== null
  ) {
    return { kind: "deck", playlistId: item.playlist_id };
  }
  if (item.section === "library" && item.playlist_id !== null) {
    return { kind: "playlist", playlistId: item.playlist_id };
  }
  if (item.section === "frontier" && item.genre !== null) {
    return { kind: "frontier", genre: item.genre };
  }
  return null;
}

const MONTHS = [
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

/** "WEEK OF 06 JUL 2026" from an ISO week-start timestamp. */
export function weekLabel(weekStart: string): string {
  const [year, month, day] = weekStart.slice(0, 10).split("-");
  const monthName = MONTHS[Number(month) - 1] ?? month;
  return `WEEK OF ${day} ${monthName} ${year}`;
}
