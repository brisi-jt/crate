/**
 * Pure wheel-event helpers for canvas pan/zoom discrimination.
 *
 * No DOM dependencies — all functions operate on plain numbers so they
 * are trivially testable and shareable across all three canvas modes
 * (graph, field, galaxy).
 *
 * Semantics (Figma-style):
 *   - ctrlKey wheel (pinch gesture on trackpad, or Ctrl+scroll on mouse)
 *     → ZOOM centred on cursor
 *   - plain wheel (two-finger swipe on trackpad, or plain scroll on mouse)
 *     → PAN the camera
 *
 * Mouse users: plain scroll now pans vertically rather than zooming.
 * This is an accepted trade-off; use Ctrl+scroll or pinch to zoom.
 */

/** Multiply raw delta values for non-pixel deltaMode values. */
const LINE_PX = 16;
const PAGE_PX = 400;

/**
 * Normalise a raw WheelEvent delta to approximate pixel units.
 *
 * @param rawDelta  - The raw deltaX, deltaY, or deltaZ value from the event.
 * @param deltaMode - WheelEvent.deltaMode (0=pixel, 1=line, 2=page).
 */
export function normaliseDelta(rawDelta: number, deltaMode: number): number {
  switch (deltaMode) {
    case 1:
      return rawDelta * LINE_PX;
    case 2:
      return rawDelta * PAGE_PX;
    default:
      // 0 = pixel, and unknown future modes fall through to no scaling.
      return rawDelta;
  }
}

/**
 * Classify a wheel event as a zoom or pan gesture.
 *
 * The browser sets ctrlKey=true for trackpad pinch gestures (and for
 * explicit Ctrl+scroll). Everything else is a pan swipe.
 */
export function classifyWheelEvent(ctrlKey: boolean): "zoom" | "pan" {
  return ctrlKey ? "zoom" : "pan";
}

/**
 * Convert a screen-pixel scroll delta to a graph-coordinate pan delta.
 *
 * Graph coords = screen pixels / zoom level k.
 *
 * @param screenDelta - Normalised pixel delta from the wheel event.
 * @param k           - Current camera zoom level (from fg.zoom()).
 */
export function panDelta(screenDelta: number, k: number): number {
  return screenDelta / k;
}

/**
 * Compute a multiplicative zoom factor from a wheel deltaY.
 *
 * Uses the same exponential curve as Figma / most canvas editors.
 * Positive deltaY (scroll down / pinch open) → factor < 1 (zoom out).
 * Negative deltaY (scroll up / pinch close) → factor > 1 (zoom in).
 *
 * The magic constant 0.001 gives a smooth ~10% zoom per 100px of delta,
 * matching the feel of native map applications.
 *
 * @param deltaY - Normalised pixel deltaY from the wheel event.
 */
export function zoomFactor(deltaY: number): number {
  return 1.001 ** -deltaY;
}
