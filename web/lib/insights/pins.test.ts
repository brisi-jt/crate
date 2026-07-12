import { describe, expect, it } from "vitest";
import type { GraphNode, InsightPin } from "@/lib/api/schemas";
import { humanizeToken, resolvePins, visiblePins } from "./pins";

function pin(anchor: string, metric_ref: string, id = anchor): InsightPin {
  return {
    anchor,
    metric_ref,
    line: "a reading",
    dismissible_id: `s:${id}:${metric_ref}`,
    salience: 0.5,
  };
}

const nodes: GraphNode[] = [
  { id: 7, name: "Old Mixes", track_count: 40, centroid: null },
];

describe("resolvePins", () => {
  it("resolves a playlist anchor to its name and open target", () => {
    const [r] = resolvePins([pin("playlist:7", "dormancy")], nodes);
    expect(r.anchorLabel).toBe("Old Mixes");
    expect(r.target).toEqual({ kind: "playlist", id: 7 });
  });

  it("falls back to a synthetic name for an unknown playlist id", () => {
    const [r] = resolvePins([pin("playlist:99", "dormancy")], nodes);
    expect(r.anchorLabel).toBe("Playlist 99");
    expect(r.target).toEqual({ kind: "playlist", id: 99 });
  });

  it("resolves a genre anchor without a target", () => {
    const [r] = resolvePins(
      [pin("genre:deep string quartet", "rarity")],
      nodes,
    );
    expect(r.anchorLabel).toBe("deep string quartet");
    expect(r.target).toEqual({ kind: "none" });
  });

  it("humanizes a quadrant region anchor", () => {
    const [r] = resolvePins([pin("quadrant:happy_energetic", "mood")], nodes);
    expect(r.anchorLabel).toBe("Happy energetic");
    expect(r.target).toEqual({ kind: "none" });
  });

  it("treats a bare fingerprint axis as a region, not an artist", () => {
    const [r] = resolvePins([pin("energy", "fingerprint")], nodes);
    expect(r.anchorLabel).toBe("Energy");
    expect(r.target).toEqual({ kind: "none" });
  });

  it("treats an unmatched anchor as an artist key on the galaxy surface", () => {
    const [r] = resolvePins([pin("aphex twin", "bridge")], nodes);
    expect(r.anchorLabel).toBe("Aphex twin");
    expect(r.target).toEqual({ kind: "artist", id: "aphex twin" });
  });

  it("preserves the API's salience ordering", () => {
    const resolved = resolvePins(
      [pin("energy", "fingerprint", "a"), pin("valence", "fingerprint", "b")],
      nodes,
    );
    expect(resolved.map((r) => r.pin.anchor)).toEqual(["energy", "valence"]);
  });
});

describe("visiblePins", () => {
  it("filters dismissed ids and caps at max", () => {
    const resolved = resolvePins(
      [
        pin("energy", "fingerprint", "a"),
        pin("valence", "fingerprint", "b"),
        pin("tempo", "fingerprint", "c"),
      ],
      nodes,
    );
    const dismissed = new Set(["s:a:fingerprint"]);
    const shown = visiblePins(resolved, dismissed, 1);
    expect(shown).toHaveLength(1);
    expect(shown[0].pin.anchor).toBe("valence");
  });
});

describe("humanizeToken", () => {
  it("replaces underscores and colons and capitalizes", () => {
    expect(humanizeToken("happy_energetic")).toBe("Happy energetic");
    expect(humanizeToken("region:north")).toBe("Region north");
  });
});
