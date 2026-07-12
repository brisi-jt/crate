"use client";

import { useMemo } from "react";
import type { CamelotSegment } from "@/lib/api/schemas";
import { keyTint, wheelSegments } from "@/lib/insights/camelot";
import { polar } from "@/lib/insights/fingerprint";

interface CamelotWheelProps {
  camelot: CamelotSegment[];
  size?: number;
}

/**
 * The Camelot harmonic-mixing wheel, populated by the library. Two rings
 * (A inner / B outer), each occupied code an annular sector whose fill
 * lightens with track count and tints with mean valence. Empty codes are
 * simply absent — the wheel reads with honest gaps.
 */
export function CamelotWheel({ camelot, size = 220 }: CamelotWheelProps) {
  const cx = size / 2;
  const cy = size / 2;
  const innerR = size * 0.16;
  const midR = size * 0.3;
  const outerR = size * 0.44;

  const segments = useMemo(
    () => wheelSegments(camelot, cx, cy, innerR, midR, outerR),
    [camelot, cx, cy, innerR, midR, outerR],
  );

  if (segments.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-md border border-border-subtle border-dashed"
        style={{ width: size, height: size }}
      >
        <span className="micro-caps text-text-muted">NO KEYS YET</span>
      </div>
    );
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="Camelot key wheel"
    >
      <title>
        Camelot wheel — track distribution across the 24 harmonic keys
      </title>

      {segments.map((s) => (
        <path
          key={s.code}
          d={s.path}
          fill={keyTint(s.meanValence)}
          fillOpacity={0.25 + 0.65 * s.intensity}
          stroke="var(--border-subtle)"
          strokeWidth={0.5}
        />
      ))}

      {/* Number labels around the outer ring */}
      {Array.from({ length: 12 }, (_, i) => {
        const number = i + 1;
        const angle = i * (Math.PI / 6);
        const p = polar(cx, cy, outerR + 12, angle);
        return (
          <text
            key={number}
            x={p.x}
            y={p.y}
            textAnchor="middle"
            dominantBaseline="middle"
            className="data-readout"
            fontSize={9}
            fill="var(--text-muted)"
          >
            {number}
          </text>
        );
      })}
    </svg>
  );
}
