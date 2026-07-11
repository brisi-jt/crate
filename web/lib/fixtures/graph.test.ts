import { describe, expect, it } from "vitest";
import { graphResponseSchema } from "@/lib/api/schemas";
import { acousticColor } from "@/lib/color/acoustic";
import { graphFixture } from "./graph";

describe("graph fixture", () => {
  it("parses through the graph contract schema", () => {
    const parsed = graphResponseSchema.parse(graphFixture);
    expect(parsed.nodes).toHaveLength(14);
    expect(parsed.edges).toHaveLength(16);
  });

  it("every edge references known nodes", () => {
    const ids = new Set(graphFixture.nodes.map((n) => n.id));
    for (const edge of graphFixture.edges) {
      expect(ids.has(edge.source)).toBe(true);
      expect(ids.has(edge.target)).toBe(true);
    }
  });

  it("contains exactly one subset edge and one grey node", () => {
    expect(graphFixture.edges.filter((e) => e.subset)).toHaveLength(1);
    expect(graphFixture.nodes.filter((n) => n.centroid === null)).toHaveLength(
      1,
    );
  });

  it("centroids reproduce the tokens-doc swatches", () => {
    // Extended examples from the tokens doc §2 (rounded there, tolerance here).
    const expectations: Record<string, { l: number; c: number; h: number }> = {
      "Indie Rock": { l: 0.63, c: 0.128, h: 338 },
      "Late Night Jazz": { l: 0.56, c: 0.076, h: 61 },
      "Hip-Hop": { l: 0.615, c: 0.148, h: 314 },
      Ambient: { l: 0.55, c: 0.063, h: 347 },
      Pop: { l: 0.71, c: 0.167, h: 302 },
      Techno: { l: 0.575, c: 0.154, h: 290 },
      "Gym Warmup": { l: 0.66, c: 0.15, h: 289 },
    };
    for (const [name, expected] of Object.entries(expectations)) {
      const node = graphFixture.nodes.find((n) => n.name === name);
      expect(node?.centroid, name).toBeTruthy();
      const centroid = node?.centroid;
      if (!centroid) continue;
      const color = acousticColor(centroid);
      expect(color.l, `${name} L`).toBeCloseTo(expected.l, 2);
      expect(color.c, `${name} c`).toBeCloseTo(expected.c, 2);
      expect(Math.abs(color.h - expected.h), `${name} h`).toBeLessThanOrEqual(
        1,
      );
    }
  });
});
