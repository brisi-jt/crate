import { describe, expect, it } from "vitest";
import { queueParams } from "./queue-params";

describe("triage queue param mapping", () => {
  it("liked mode sends the slider value as max_playlists", () => {
    expect(
      queueParams({ source: "liked", maxPlaylists: 0, offset: 0 }),
    ).toEqual({ limit: 50, offset: 0, max_playlists: 0 });
    expect(
      queueParams({ source: "liked", maxPlaylists: 3, offset: 0 }),
    ).toEqual({ limit: 50, offset: 0, max_playlists: 3 });
  });

  it("playlist mode omits max_playlists (the slider is liked-only)", () => {
    const params = queueParams({
      source: "playlist",
      maxPlaylists: 2,
      offset: 100,
    });
    expect(params.max_playlists).toBeUndefined();
    expect(params).toEqual({ limit: 50, offset: 100 });
  });

  it("carries pagination offset through", () => {
    expect(
      queueParams({ source: "liked", maxPlaylists: 0, offset: 150 }).offset,
    ).toBe(150);
  });

  it("clamps a negative slider value to zero", () => {
    expect(
      queueParams({ source: "liked", maxPlaylists: -5, offset: 0 })
        .max_playlists,
    ).toBe(0);
  });
});
