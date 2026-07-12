import { describe, expect, it } from "vitest";
import type { CamelotSegment } from "@/lib/api/schemas";
import { keyTint, wheelSegments } from "./camelot";

function seg(
  code: string,
  number: number,
  ring: string,
  count: number,
  mean_valence: number | null = 0.5,
): CamelotSegment {
  return { code, number, ring, count, mean_valence };
}

describe("wheelSegments", () => {
  it("returns one sector per occupied code", () => {
    const segs = wheelSegments(
      [seg("1A", 1, "A", 12), seg("8B", 8, "B", 4)],
      100,
      100,
      20,
      40,
      60,
    );
    expect(segs).toHaveLength(2);
    expect(segs[0].code).toBe("1A");
    expect(segs[0].path).toMatch(/^M /);
  });

  it("normalizes intensity against the busiest code", () => {
    const segs = wheelSegments(
      [seg("1A", 1, "A", 100), seg("2A", 2, "A", 25)],
      0,
      0,
      20,
      40,
      60,
    );
    expect(segs[0].intensity).toBeCloseTo(1);
    expect(segs[1].intensity).toBeCloseTo(0.25);
  });

  it("puts number 1 at the top (12 o'clock)", () => {
    const [s] = wheelSegments([seg("1A", 1, "A", 5)], 0, 0, 20, 40, 60);
    // sector spans -15°..+15°, so mid angle is ~0 (straight up)
    expect(s.midAngle).toBeCloseTo(0, 5);
  });

  it("assigns ring A inside ring B", () => {
    const [a] = wheelSegments([seg("1A", 1, "A", 5)], 0, 0, 20, 40, 60);
    const [b] = wheelSegments([seg("1B", 1, "B", 5)], 0, 0, 20, 40, 60);
    expect(a.ring).toBe("A");
    expect(b.ring).toBe("B");
  });
});

describe("keyTint", () => {
  it("greys a key with no mean valence", () => {
    expect(keyTint(null)).toMatch(/oklch\(0\.42/);
  });

  it("brightens with valence", () => {
    const low = keyTint(0);
    const high = keyTint(1);
    expect(low).not.toBe(high);
    expect(high).toMatch(/^oklch\(/);
  });
});
