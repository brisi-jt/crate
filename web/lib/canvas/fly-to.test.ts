import { describe, expect, it } from "vitest";
import {
  bumpFlyTo,
  type FlyTarget,
  flyToForMode,
  shouldFireFlyTo,
} from "./fly-to";

/**
 * G5 — search-to-focus fly-to. ⌘K search dispatches a fly-to target (mode + id
 * + monotonic nonce); each canvas consumes only the target for its own mode and
 * fires once per nonce. Pure state so "fire once, re-fire on repeat search,
 * ignore other-mode targets" is unit-tested.
 */

describe("bumpFlyTo", () => {
  it("creates a first target with nonce 1", () => {
    const t = bumpFlyTo(null, { mode: "tracks", id: 42 });
    expect(t).toEqual({ mode: "tracks", id: 42, nonce: 1 });
  });

  it("increments the nonce so the same node re-fires", () => {
    const first = bumpFlyTo(null, { mode: "tracks", id: 42 });
    const again = bumpFlyTo(first, { mode: "tracks", id: 42 });
    expect(again.nonce).toBe(2);
    expect(again.id).toBe(42);
  });

  it("keeps the nonce monotonic across a mode switch", () => {
    const a = bumpFlyTo(null, { mode: "tracks", id: 1 });
    const b = bumpFlyTo(a, { mode: "artists", id: "m83" });
    expect(b.nonce).toBe(2);
    expect(b.mode).toBe("artists");
    expect(b.id).toBe("m83");
  });
});

describe("flyToForMode", () => {
  const target: FlyTarget = { mode: "tracks", id: 42, nonce: 3 };

  it("returns the target when the mode matches", () => {
    expect(flyToForMode(target, "tracks")).toEqual(target);
  });

  it("returns null for a different mode (canvas ignores it)", () => {
    expect(flyToForMode(target, "artists")).toBeNull();
    expect(flyToForMode(target, "playlists")).toBeNull();
  });

  it("returns null when there is no target", () => {
    expect(flyToForMode(null, "tracks")).toBeNull();
  });
});

describe("shouldFireFlyTo", () => {
  it("fires when the nonce is newer than the last fired", () => {
    expect(shouldFireFlyTo({ nonce: 3 }, 2)).toBe(true);
  });

  it("does not fire the same nonce twice", () => {
    expect(shouldFireFlyTo({ nonce: 3 }, 3)).toBe(false);
  });

  it("does not fire a stale nonce", () => {
    expect(shouldFireFlyTo({ nonce: 2 }, 5)).toBe(false);
  });

  it("does not fire when there is no target", () => {
    expect(shouldFireFlyTo(null, 0)).toBe(false);
  });
});
