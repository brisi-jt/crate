/**
 * The destinations-management view's selection state. Spotify's API can't see
 * playlist folders, so this is the crate-native way to scope which owned
 * playlists are filing destinations. A playlist is either eligible (checked) or
 * held out of triage; the PUT sends the excluded set (the unchecked ones).
 *
 * Pure, so the toggle / all / none / invert bulk ops — and the fact that all/
 * none/invert act only on the currently search-filtered set — are testable
 * without a component.
 */

export interface Destination {
  id: number;
  name: string;
  excluded: boolean;
}

export interface DestinationsState {
  order: number[]; // playlist ids in server order
  names: Record<number, string>;
  eligible: Record<number, boolean>; // true = a filing destination
  initial: Record<number, boolean>; // the loaded eligibility, for dirty checks
  search: string;
}

export type DestinationsEvent =
  | { type: "TOGGLE"; id: number }
  | { type: "SEARCH"; query: string }
  | { type: "SELECT_ALL" } // mark every VISIBLE playlist eligible
  | { type: "SELECT_NONE" } // hold every VISIBLE playlist out of triage
  | { type: "INVERT" }; // flip every VISIBLE playlist

export function initDestinations(
  destinations: Destination[],
): DestinationsState {
  const order: number[] = [];
  const names: Record<number, string> = {};
  const eligible: Record<number, boolean> = {};
  for (const d of destinations) {
    order.push(d.id);
    names[d.id] = d.name;
    eligible[d.id] = !d.excluded; // eligible is the inverse of excluded
  }
  return { order, names, eligible, initial: { ...eligible }, search: "" };
}

export function filterDestinations(
  destinations: Destination[],
  query: string,
): Destination[] {
  const q = query.trim().toLowerCase();
  if (!q) return destinations;
  return destinations.filter((d) => d.name.toLowerCase().includes(q));
}

/** The ids currently shown given the search — the target of the bulk ops. */
export function visibleIds(state: DestinationsState): number[] {
  const q = state.search.trim().toLowerCase();
  if (!q) return [...state.order];
  return state.order.filter((id) =>
    (state.names[id] ?? "").toLowerCase().includes(q),
  );
}

export function reduceDestinations(
  state: DestinationsState,
  event: DestinationsEvent,
): DestinationsState {
  switch (event.type) {
    case "TOGGLE":
      return {
        ...state,
        eligible: { ...state.eligible, [event.id]: !state.eligible[event.id] },
      };
    case "SEARCH":
      return { ...state, search: event.query };
    case "SELECT_ALL":
      return setVisible(state, () => true);
    case "SELECT_NONE":
      return setVisible(state, () => false);
    case "INVERT":
      return setVisible(state, (id) => !state.eligible[id]);
  }
}

function setVisible(
  state: DestinationsState,
  next: (id: number) => boolean,
): DestinationsState {
  const eligible = { ...state.eligible };
  for (const id of visibleIds(state)) eligible[id] = next(id);
  return { ...state, eligible };
}

export function eligibleCount(state: DestinationsState): number {
  return state.order.filter((id) => state.eligible[id]).length;
}

/** The playlists held out of triage — the PUT payload, sorted for stability. */
export function excludedIds(state: DestinationsState): number[] {
  return state.order.filter((id) => !state.eligible[id]).sort((a, b) => a - b);
}

export function isDirty(state: DestinationsState): boolean {
  return state.order.some((id) => state.eligible[id] !== state.initial[id]);
}

export interface DestinationsBody {
  excluded_playlist_ids: number[];
}

export function destinationsBody(state: DestinationsState): DestinationsBody {
  return { excluded_playlist_ids: excludedIds(state) };
}
