/**
 * Pure helpers behind the <Explain> affordance — extracted so the a11y label,
 * the trigger glyph, and the reduced-motion decision are unit-testable without
 * a DOM. The component (components/explain/explain.tsx) is a thin shell over
 * these.
 */

import { resolveExplain } from "./glossary";

/**
 * The accessible name for the explain trigger. Screen readers announce which
 * metric is about to be explained, not a bare "button".
 */
export function explainTriggerLabel(metric: string): string {
  const entry = resolveExplain(metric);
  return entry ? `Explain: ${entry.term}` : "Explain this metric";
}

/**
 * The trigger glyph — the same hushed question mark the field guide uses, so
 * the affordance reads consistently across the app.
 */
export function explainTriggerGlyph(): string {
  return "?";
}

export interface OpenTransition {
  duration: number;
  ease: readonly number[];
}

/**
 * The open transition for the explain card. Ease-out-quint by default; under
 * `prefers-reduced-motion` it becomes instant (zero duration), so the card
 * still appears but never animates.
 */
export function openTransition(reducedMotion: boolean): OpenTransition {
  if (reducedMotion) {
    return { duration: 0, ease: [0, 0, 1, 1] };
  }
  return { duration: 0.18, ease: [0.16, 1, 0.3, 1] };
}
