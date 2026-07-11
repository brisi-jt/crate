import { describe, expect, it } from "vitest";
import { acousticColor, GREY_NODE } from "@/lib/color/acoustic";
import { meanCentroid, pointColor } from "./color";

const GYM = { acousticness: 0.05, energy: 0.97, valence: 0.7 };
const FOLK = { acousticness: 0.95, energy: 0.15, valence: 0.45 };

describe("pointColor", () => {
  it("uses per-track features when the payload ships them", () => {
    // Features win even when owner centroids disagree.
    expect(pointColor(GYM, [FOLK])).toEqual(acousticColor(GYM));
  });

  it("falls back to the single owning playlist's exact color", () => {
    expect(pointColor(null, [FOLK])).toEqual(acousticColor(FOLK));
    expect(pointColor(undefined, [GYM])).toEqual(acousticColor(GYM));
  });

  it("blends multi-membership tracks in centroid space, not color space", () => {
    const expected = acousticColor({
      acousticness: (0.05 + 0.95) / 2,
      energy: (0.97 + 0.15) / 2,
      valence: (0.7 + 0.45) / 2,
    });
    expect(pointColor(null, [GYM, FOLK])).toEqual(expected);
  });

  it("ignores unenriched owners in the blend", () => {
    expect(pointColor(null, [null, FOLK])).toEqual(acousticColor(FOLK));
  });

  it("renders the grey out-of-gamut state with no usable source", () => {
    expect(pointColor(null, [])).toEqual(GREY_NODE);
    expect(pointColor(null, [null])).toEqual(GREY_NODE);
  });
});

describe("meanCentroid", () => {
  it("averages each axis over enriched owners only", () => {
    const mean = meanCentroid([GYM, FOLK, null]);
    expect(mean).toEqual({
      acousticness: 0.5,
      energy: (0.97 + 0.15) / 2,
      valence: (0.7 + 0.45) / 2,
    });
  });

  it("returns null when nothing is enriched", () => {
    expect(meanCentroid([null])).toBeNull();
  });
});
