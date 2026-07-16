import { describe, expect, it } from "vitest";
import {
  initialRetryState,
  isPreviewStaleError,
} from "@/lib/playback/preview-refresh";

// MediaError is a browser API — define a minimal stand-in for the test env.
const MEDIA_ERR_ABORTED = 1;
const MEDIA_ERR_NETWORK = 2;
const MEDIA_ERR_DECODE = 3;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4;

function fakeMediaError(code: number): MediaError {
  return { code, message: "" } as MediaError;
}

describe("isPreviewStaleError", () => {
  it("returns false for null / undefined", () => {
    expect(isPreviewStaleError(null)).toBe(false);
    expect(isPreviewStaleError(undefined)).toBe(false);
  });

  it("returns true for MEDIA_ERR_NETWORK (CDN 403 on stale URL)", () => {
    expect(isPreviewStaleError(fakeMediaError(MEDIA_ERR_NETWORK))).toBe(true);
  });

  it("returns true for MEDIA_ERR_SRC_NOT_SUPPORTED (alt UA/CDN 403 shape)", () => {
    expect(
      isPreviewStaleError(fakeMediaError(MEDIA_ERR_SRC_NOT_SUPPORTED)),
    ).toBe(true);
  });

  it("returns false for MEDIA_ERR_ABORTED (user-initiated stop)", () => {
    expect(isPreviewStaleError(fakeMediaError(MEDIA_ERR_ABORTED))).toBe(false);
  });

  it("returns false for MEDIA_ERR_DECODE (broken audio data — not a 403)", () => {
    expect(isPreviewStaleError(fakeMediaError(MEDIA_ERR_DECODE))).toBe(false);
  });
});

describe("initialRetryState", () => {
  it("starts with attempted=false", () => {
    expect(initialRetryState()).toEqual({ attempted: false });
  });

  it("each call returns a fresh object", () => {
    const a = initialRetryState();
    const b = initialRetryState();
    expect(a).not.toBe(b);
  });
});
