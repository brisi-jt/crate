import { describe, expect, it } from "vitest";
import { acousticColor, GREY_NODE } from "@/lib/color/acoustic";
import {
  clusterPalette,
  equalizedColor,
  rankEqualize,
} from "@/lib/color/equalize";
import { fieldPointColor, meanCentroid, pointColor } from "./color";

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

describe("fieldPointColor (G4 palette modes)", () => {
  const lib = [GYM, FOLK, { acousticness: 0.5, energy: 0.5, valence: 0.5 }];
  const eq = rankEqualize(lib);
  const palette = clusterPalette([0, 1], -1);

  it("acoustic mode uses the equalized colour for a track with features", () => {
    const col = fieldPointColor({
      mode: "acoustic",
      features: GYM,
      owners: [],
      cluster: 0,
      equalizer: eq,
      palette,
    });
    expect(col).toEqual(equalizedColor(GYM, eq));
  });

  it("acoustic mode with no equalizer falls back to the raw acoustic colour", () => {
    const col = fieldPointColor({
      mode: "acoustic",
      features: GYM,
      owners: [],
      cluster: 0,
      equalizer: null,
      palette,
    });
    expect(col).toEqual(acousticColor(GYM));
  });

  it("cluster mode keys colour off the cluster, shaded by acoustics", () => {
    const col = fieldPointColor({
      mode: "cluster",
      features: GYM,
      owners: [],
      cluster: 1,
      equalizer: eq,
      palette,
    });
    expect(col).toEqual(palette.colorFor(1, GYM));
  });

  it("cluster mode uses neutral centroid for unenriched tracks", () => {
    // No features → cluster colour still renders (neutral acoustics 0.5).
    const col = fieldPointColor({
      mode: "cluster",
      features: null,
      owners: [],
      cluster: 1,
      equalizer: eq,
      palette,
    });
    expect(col.h).toBeCloseTo(palette.baseHue(1), 6);
  });

  it("greys a track with no source in acoustic mode", () => {
    const col = fieldPointColor({
      mode: "acoustic",
      features: null,
      owners: [],
      cluster: -1,
      equalizer: eq,
      palette,
    });
    expect(col).toEqual(GREY_NODE);
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
