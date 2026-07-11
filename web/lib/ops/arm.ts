/**
 * ARM → COMMIT switchgear state machine (design brief D7, tier 2).
 *
 * Pure reducer so the safety behavior is unit-testable: arming opens a 10s
 * commit window with a visible decay; any manifest or expression edit
 * disarms; commit consumes the arm. Time flows in via event payloads — the
 * component drives it with an interval, tests drive it directly.
 */

export const ARM_DECAY_MS = 10_000;

export type ArmState =
  | { phase: "idle" }
  | { phase: "armed"; armedAt: number; expiresAt: number };

export type ArmEvent =
  | { type: "arm"; now: number }
  | { type: "disarm" }
  | { type: "tick"; now: number }
  | { type: "manifest-changed" }
  | { type: "commit" };

export const IDLE: ArmState = { phase: "idle" };

export function armReducer(state: ArmState, event: ArmEvent): ArmState {
  switch (event.type) {
    case "arm":
      return {
        phase: "armed",
        armedAt: event.now,
        expiresAt: event.now + ARM_DECAY_MS,
      };
    case "disarm":
    case "manifest-changed":
    case "commit":
      return IDLE;
    case "tick":
      if (state.phase === "armed" && event.now >= state.expiresAt) {
        return IDLE;
      }
      return state;
  }
}

/** Whole seconds left on the arm window; null when idle. */
export function secondsRemaining(state: ArmState, now: number): number | null {
  if (state.phase !== "armed") return null;
  return Math.max(0, Math.ceil((state.expiresAt - now) / 1000));
}

export function isArmed(state: ArmState): boolean {
  return state.phase === "armed";
}
