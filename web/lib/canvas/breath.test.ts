import { describe, expect, it } from "vitest";
import {
  DRIFT_AMPLITUDE,
  DRIFT_FRAME_MS,
  driftOffset,
  driftPhase,
  SECOND_TONE_RATIO,
  shouldStepDrift,
} from "./breath";

const PEAK = DRIFT_AMPLITUDE * (1 + SECOND_TONE_RATIO);

describe("driftPhase", () => {
  it("is deterministic for the same seed", () => {
    expect(driftPhase("abc")).toBe(driftPhase("abc"));
    expect(driftPhase(42)).toBe(driftPhase(42));
  });

  it("differs across seeds (no lock-step)", () => {
    expect(driftPhase("a")).not.toBe(driftPhase("b"));
    expect(driftPhase(1)).not.toBe(driftPhase(2));
  });

  it("stays within [0, 2π)", () => {
    for (const seed of ["", "x", "playlist-17", "9999", "🎵"]) {
      const p = driftPhase(seed);
      expect(p).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThan(Math.PI * 2);
    }
  });
});

describe("driftOffset", () => {
  it("is bounded by the two-tone peak on both axes", () => {
    const phase = driftPhase("node-1");
    for (let t = 0; t < 200_000; t += 137) {
      const { dx, dy } = driftOffset(t, phase);
      expect(Math.abs(dx)).toBeLessThanOrEqual(PEAK + 1e-9);
      expect(Math.abs(dy)).toBeLessThanOrEqual(PEAK + 1e-9);
    }
  });

  it("moves a clearly-visible amount in a TYPICAL 2s window (the freeze regression)", () => {
    // The prior random-walk breath netted ~0.2 units over 2s (sub-pixel), and a
    // burst of panning drove that to ~0 for ALL nodes at once — the freeze the
    // user saw. Deterministic per-node drift must travel a visible amount in
    // the median 2s window so the graph never reads as static. At zoom≈1 these
    // units are screen pixels. (A single node can be momentarily stationary at
    // a turning point; that is fine because every node carries a different
    // phase — see the next test — so the graph as a whole is always in motion.)
    const phase = driftPhase("node-freeze");
    const nets: number[] = [];
    for (let start = 0; start < 120_000; start += 250) {
      const a = driftOffset(start, phase);
      const b = driftOffset(start + 2000, phase);
      nets.push(Math.hypot(b.dx - a.dx, b.dy - a.dy));
    }
    nets.sort((x, y) => x - y);
    const median = nets[Math.floor(nets.length / 2)];
    const p90 = nets[Math.floor(nets.length * 0.9)];
    // Median window travels several px; a busy window travels a lot.
    expect(median).toBeGreaterThan(5);
    expect(p90).toBeGreaterThan(12);
  });

  it("keeps the WHOLE graph moving: across many node phases, some node always drifts", () => {
    // The real freeze was every node stationary at once. With distinct phases
    // per node, at every 2s window at least one node moves clearly — so the
    // aggregate canvas is never frozen, whatever the sampling.
    const phases = Array.from({ length: 40 }, (_, i) => driftPhase(`n${i}`));
    for (let start = 0; start < 120_000; start += 500) {
      let best = 0;
      for (const p of phases) {
        const a = driftOffset(start, p);
        const b = driftOffset(start + 2000, p);
        best = Math.max(best, Math.hypot(b.dx - a.dx, b.dy - a.dy));
      }
      expect(best).toBeGreaterThan(5);
    }
  });

  it("does not net to zero over time (unlike the random walk)", () => {
    // Average absolute per-axis offset over a long span is a good fraction of
    // the amplitude — the node genuinely ranges, it does not hover at rest.
    const phase = driftPhase("ranging");
    let sumAbs = 0;
    let n = 0;
    for (let t = 0; t < 120_000; t += 97) {
      const { dx } = driftOffset(t, phase);
      sumAbs += Math.abs(dx);
      n++;
    }
    const meanAbs = sumAbs / n;
    // Well above zero — the node ranges across a real span, not a jitter at rest.
    expect(meanAbs).toBeGreaterThan(DRIFT_AMPLITUDE * 0.4);
  });

  it("respects a custom amplitude (scales the whole two-tone offset)", () => {
    const phase = driftPhase("amp");
    const bound = 1 * (1 + SECOND_TONE_RATIO);
    for (let t = 0; t < 50_000; t += 211) {
      const { dx, dy } = driftOffset(t, phase, 1);
      expect(Math.abs(dx)).toBeLessThanOrEqual(bound + 1e-9);
      expect(Math.abs(dy)).toBeLessThanOrEqual(bound + 1e-9);
    }
  });

  it("two nodes are not in lock-step", () => {
    const p1 = driftPhase("n1");
    const p2 = driftPhase("n2");
    let anyDifferent = false;
    for (let t = 0; t < 10_000; t += 250) {
      const a = driftOffset(t, p1);
      const b = driftOffset(t, p2);
      if (Math.abs(a.dx - b.dx) > 0.1 || Math.abs(a.dy - b.dy) > 0.1) {
        anyDifferent = true;
        break;
      }
    }
    expect(anyDifferent).toBe(true);
  });
});

describe("shouldStepDrift", () => {
  it("throttles to the target frame interval", () => {
    expect(shouldStepDrift(1000, 1000)).toBe(false);
    expect(shouldStepDrift(1000 + DRIFT_FRAME_MS - 2, 1000)).toBe(false);
    expect(shouldStepDrift(1000 + DRIFT_FRAME_MS + 1, 1000)).toBe(true);
    expect(shouldStepDrift(1000 + DRIFT_FRAME_MS + 100, 1000)).toBe(true);
  });
});
