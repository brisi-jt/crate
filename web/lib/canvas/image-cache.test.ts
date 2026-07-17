import { beforeEach, describe, expect, it, vi } from "vitest";
import { createImageCache, type ImageLoader } from "./image-cache";

/**
 * G1 — hover-card image LRU. Album art / artist photos / playlist covers are
 * decoded lazily on hover dwell and cached, capped at ≤200 decoded thumbs so a
 * long session never accumulates unbounded bitmaps. The cache is a pure
 * structure (loader injected) so eviction and dedupe are unit-tested without a
 * DOM.
 */

// A fake loader that resolves immediately with a sentinel "image" per url.
function fakeLoader(): ImageLoader & { calls: string[] } {
  const calls: string[] = [];
  const load: ImageLoader = (url) => {
    calls.push(url);
    return {
      // A stand-in for HTMLImageElement — the cache only stores + returns it.
      src: url,
      complete: true,
    } as unknown as HTMLImageElement;
  };
  return Object.assign(load, { calls });
}

describe("createImageCache", () => {
  let loader: ImageLoader & { calls: string[] };

  beforeEach(() => {
    loader = fakeLoader();
  });

  it("loads a url once and returns the same element on repeat gets", () => {
    const cache = createImageCache({ capacity: 10, load: loader });
    const a = cache.get("a.jpg");
    const b = cache.get("a.jpg");
    expect(a).toBe(b);
    expect(loader.calls).toEqual(["a.jpg"]);
  });

  it("returns null and does not load for a null/empty url", () => {
    const cache = createImageCache({ capacity: 10, load: loader });
    expect(cache.get(null)).toBeNull();
    expect(cache.get("")).toBeNull();
    expect(loader.calls).toEqual([]);
  });

  it("evicts the least-recently-used entry past capacity", () => {
    const cache = createImageCache({ capacity: 2, load: loader });
    cache.get("a"); // [a]
    cache.get("b"); // [a, b]
    cache.get("c"); // evicts a → [b, c]
    expect(cache.has("a")).toBe(false);
    expect(cache.has("b")).toBe(true);
    expect(cache.has("c")).toBe(true);
    expect(cache.size).toBe(2);
  });

  it("a get promotes the entry to most-recently-used", () => {
    const cache = createImageCache({ capacity: 2, load: loader });
    cache.get("a"); // [a]
    cache.get("b"); // [a, b]
    cache.get("a"); // touch a → [b, a]
    cache.get("c"); // evicts b (LRU) → [a, c]
    expect(cache.has("a")).toBe(true);
    expect(cache.has("b")).toBe(false);
    expect(cache.has("c")).toBe(true);
  });

  it("never re-loads a still-cached url even after promotion churn", () => {
    const cache = createImageCache({ capacity: 3, load: loader });
    for (let i = 0; i < 5; i++) {
      cache.get("a");
      cache.get("b");
    }
    // a and b each loaded exactly once despite repeated gets.
    expect(loader.calls.filter((u) => u === "a")).toHaveLength(1);
    expect(loader.calls.filter((u) => u === "b")).toHaveLength(1);
  });

  it("caps decoded thumbs at the ≤200 default capacity", () => {
    const cache = createImageCache({ load: loader });
    for (let i = 0; i < 250; i++) cache.get(`img-${i}`);
    expect(cache.size).toBeLessThanOrEqual(200);
    // The 50 oldest were evicted; the newest survive.
    expect(cache.has("img-249")).toBe(true);
    expect(cache.has("img-0")).toBe(false);
  });

  it("peek returns without loading or promoting", () => {
    const cache = createImageCache({ capacity: 2, load: loader });
    cache.get("a"); // [a]
    cache.get("b"); // [a, b]
    expect(cache.peek("a")?.src).toBe("a"); // no load, no promote
    expect(cache.peek("z")).toBeNull(); // not present
    cache.get("c"); // evicts a (peek didn't promote it) → [b, c]
    expect(cache.has("a")).toBe(false);
    expect(loader.calls).toEqual(["a", "b", "c"]);
  });
});

describe("cache invokes the loader with the real url", () => {
  it("passes the url through to the injected loader", () => {
    const load = vi.fn((url: string) => ({ src: url }) as HTMLImageElement);
    const cache = createImageCache({ capacity: 5, load });
    cache.get("https://cdn/x.jpg");
    expect(load).toHaveBeenCalledWith("https://cdn/x.jpg");
  });
});
