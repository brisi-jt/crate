/**
 * Camelot-wheel geometry — the harmonic-mixing dial, populated by the library.
 *
 * 12 numbers × 2 rings (A inner / B outer). Each occupied code becomes a
 * segment whose radial extent encodes track count and whose tint reads from
 * mean valence (brighter = happier). Empty codes are absent from the API, so
 * the wheel renders with gaps — honest. Pure geometry — unit-tested.
 */

import type { CamelotSegment } from "@/lib/api/schemas";

export interface WheelSegment {
  code: string;
  number: number;
  ring: "A" | "B";
  count: number;
  meanValence: number | null;
  /** Sector center angle in radians (0 = up, clockwise), for label anchoring. */
  midAngle: number;
  /** SVG path for the annular sector, filled proportional to count. */
  path: string;
  /** 0..1 count share of the busiest code (drives fill lightness/alpha). */
  intensity: number;
}

const SLICE = (2 * Math.PI) / 12; // 30° per number

/**
 * Build the wheel's occupied sectors. `number` (1..12) maps to a clock
 * position (1 at 12 o'clock, ascending clockwise). Ring A is the inner band,
 * B the outer. Radii are caller-supplied so the component controls size.
 */
export function wheelSegments(
  camelot: CamelotSegment[],
  cx: number,
  cy: number,
  innerR: number,
  midR: number,
  outerR: number,
): WheelSegment[] {
  const maxCount = camelot.reduce((m, s) => Math.max(m, s.count), 0);
  return camelot.map((seg) => {
    const ring = seg.ring === "A" ? "A" : "B";
    const startAngle = (seg.number - 1) * SLICE - SLICE / 2;
    const endAngle = startAngle + SLICE;
    const r0 = ring === "A" ? innerR : midR;
    const r1 = ring === "A" ? midR : outerR;
    return {
      code: seg.code,
      number: seg.number,
      ring,
      count: seg.count,
      meanValence: seg.mean_valence,
      midAngle: startAngle + SLICE / 2,
      path: annularSector(cx, cy, r0, r1, startAngle, endAngle),
      intensity: maxCount > 0 ? seg.count / maxCount : 0,
    };
  });
}

/** SVG path for an annular sector between two radii and two angles. */
export function annularSector(
  cx: number,
  cy: number,
  r0: number,
  r1: number,
  startAngle: number,
  endAngle: number,
): string {
  const p = (r: number, a: number) => ({
    x: cx + r * Math.sin(a),
    y: cy - r * Math.cos(a),
  });
  const large = endAngle - startAngle > Math.PI ? 1 : 0;
  const a0 = p(r1, startAngle);
  const a1 = p(r1, endAngle);
  const b1 = p(r0, endAngle);
  const b0 = p(r0, startAngle);
  return [
    `M ${round(a0.x)} ${round(a0.y)}`,
    `A ${round(r1)} ${round(r1)} 0 ${large} 1 ${round(a1.x)} ${round(a1.y)}`,
    `L ${round(b1.x)} ${round(b1.y)}`,
    `A ${round(r0)} ${round(r0)} 0 ${large} 0 ${round(b0.x)} ${round(b0.y)}`,
    "Z",
  ].join(" ");
}

/** Valence tint for a key: warm gold (low) → bright coral (high). */
export function keyTint(meanValence: number | null): string {
  if (meanValence === null) return "oklch(0.42 0.012 265)";
  const v = Math.min(1, Math.max(0, meanValence));
  const l = 0.5 + 0.22 * v;
  const h = 70 - 55 * v;
  return `oklch(${round(l, 3)} 0.11 ${round(h, 1)})`;
}

function round(x: number, places = 2): number {
  const f = 10 ** places;
  return Math.round(x * f) / f;
}
