/**
 * The listening deck's review state machine — a pure reducer so the
 * keyboard flow (space / a / x / j / k) is testable without a DOM.
 *
 * The queue holds candidate ids in rank order. Navigation clamps at the
 * ends; resolving a candidate (accept or reject) removes it and keeps the
 * review position in place; a reload (queue refetch) follows the current
 * candidate to its new rank when it survived.
 */

export interface DeckState {
  /** Candidate ids in rank order. */
  queue: number[];
  /** Index of the candidate under review. Meaningless when the queue is empty. */
  index: number;
  /** Whether audio should be playing — carried across navigation. */
  playing: boolean;
}

export type DeckEvent =
  | { type: "LOADED"; queue: number[] }
  | { type: "NEXT" }
  | { type: "PREV" }
  | { type: "TOGGLE_PLAY" }
  | { type: "RESOLVE"; id: number }
  | { type: "AUDIO_ENDED" };

export const initialDeckState: DeckState = {
  queue: [],
  index: 0,
  playing: false,
};

export function currentId(state: DeckState): number | null {
  return state.queue[state.index] ?? null;
}

function clampIndex(queue: number[], index: number): number {
  if (queue.length === 0) return 0;
  return Math.min(Math.max(index, 0), queue.length - 1);
}

export function reduce(state: DeckState, event: DeckEvent): DeckState {
  switch (event.type) {
    case "LOADED": {
      const focused = currentId(state);
      const followed = focused === null ? -1 : event.queue.indexOf(focused);
      return {
        ...state,
        queue: event.queue,
        index:
          followed >= 0
            ? followed
            : clampIndex(
                event.queue,
                Math.min(state.index, event.queue.length - 1),
              ),
      };
    }
    case "NEXT":
      return { ...state, index: clampIndex(state.queue, state.index + 1) };
    case "PREV":
      return { ...state, index: clampIndex(state.queue, state.index - 1) };
    case "TOGGLE_PLAY":
      if (state.queue.length === 0) return state;
      return { ...state, playing: !state.playing };
    case "AUDIO_ENDED":
      return { ...state, playing: false };
    case "RESOLVE": {
      const position = state.queue.indexOf(event.id);
      if (position < 0) return state;
      const queue = state.queue.filter((id) => id !== event.id);
      // Removing an earlier entry shifts the current one left by one slot.
      const index = clampIndex(
        queue,
        position < state.index ? state.index - 1 : state.index,
      );
      return { ...state, queue, index };
    }
  }
}
