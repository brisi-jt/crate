/**
 * The triage queue's review state machine — a pure reducer so the ritual
 * (skip / apply / advance) is testable without a DOM.
 *
 * Unlike the listening deck, skip does NOT remove a track: the triage queue
 * cycles, so a skipped song comes back around later — nothing is lost. Only a
 * successful apply removes its track, and the position advances in place.
 */

export interface TriageState {
  /** Track ids in queue order (oldest-waiting first). */
  queue: number[];
  /** Index of the song under review. Meaningless when the queue is empty. */
  index: number;
  /** True once the queue has been worked to empty — drives the celebration. */
  drained: boolean;
}

export type TriageEvent =
  /** Fresh queue (first page, or a source/filter switch). */
  | { type: "LOADED"; queue: number[] }
  /** A later page appended to the working queue, preserving focus. */
  | { type: "APPENDED"; queue: number[] }
  /** Move to the next song without filing this one; wraps at the tail. */
  | { type: "SKIP" }
  /** A song was successfully filed — remove it and advance in place. */
  | { type: "APPLIED"; trackId: number };

export const initialTriageState: TriageState = {
  queue: [],
  index: 0,
  drained: false,
};

export function currentTrackId(state: TriageState): number | null {
  return state.queue[state.index] ?? null;
}

function clampIndex(queue: number[], index: number): number {
  if (queue.length === 0) return 0;
  return Math.min(Math.max(index, 0), queue.length - 1);
}

export function reduceTriage(
  state: TriageState,
  event: TriageEvent,
): TriageState {
  switch (event.type) {
    case "LOADED": {
      const focused = currentTrackId(state);
      const followed = focused === null ? -1 : event.queue.indexOf(focused);
      return {
        queue: event.queue,
        index:
          followed >= 0
            ? followed
            : clampIndex(
                event.queue,
                Math.min(state.index, event.queue.length - 1),
              ),
        drained: event.queue.length === 0 ? state.drained : false,
      };
    }
    case "APPENDED": {
      const focused = currentTrackId(state);
      const queue = [...state.queue, ...event.queue];
      const followed = focused === null ? -1 : queue.indexOf(focused);
      return {
        ...state,
        queue,
        index: followed >= 0 ? followed : clampIndex(queue, state.index),
      };
    }
    case "SKIP": {
      if (state.queue.length === 0) return state;
      // Cycle: the last song wraps back to the head — a true inbox loop.
      return { ...state, index: (state.index + 1) % state.queue.length };
    }
    case "APPLIED": {
      const position = state.queue.indexOf(event.trackId);
      if (position < 0) return state;
      const queue = state.queue.filter((id) => id !== event.trackId);
      // Removing an earlier entry shifts the current one left one slot.
      const index = clampIndex(
        queue,
        position < state.index ? state.index - 1 : state.index,
      );
      return { queue, index, drained: queue.length === 0 };
    }
  }
}
