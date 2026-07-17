/**
 * G1 — hover-card image LRU cache.
 *
 * Rich hover cards show album art, artist photos, and playlist-cover mosaics.
 * Images are decoded lazily on hover dwell and cached so re-hovering is instant
 * and a long session never accumulates unbounded bitmaps. Capacity is capped
 * (≤200 decoded thumbs by default). The loader is injected so eviction/dedupe
 * are pure and unit-tested without a DOM; the browser loader lives in
 * lib/canvas/dom-image-loader.ts.
 */

/** Turns a url into a decoding image element (or a fake, in tests). */
export type ImageLoader = (url: string) => HTMLImageElement;

export interface ImageCacheOptions {
  /** Max decoded thumbs kept. Default 200. */
  capacity?: number;
  load: ImageLoader;
}

const DEFAULT_CAPACITY = 200;

export interface ImageCache {
  /** Load-or-return the image for a url, promoting it to most-recently-used. */
  get: (url: string | null | undefined) => HTMLImageElement | null;
  /** Return the cached image without loading or promoting; null if absent. */
  peek: (url: string | null | undefined) => HTMLImageElement | null;
  has: (url: string) => boolean;
  readonly size: number;
}

export function createImageCache(options: ImageCacheOptions): ImageCache {
  const capacity = options.capacity ?? DEFAULT_CAPACITY;
  const { load } = options;
  // Map preserves insertion order; we re-insert on touch so the first key is
  // always the least-recently-used candidate for eviction.
  const store = new Map<string, HTMLImageElement>();

  function evictIfNeeded() {
    while (store.size > capacity) {
      const oldest = store.keys().next().value;
      if (oldest === undefined) break;
      store.delete(oldest);
    }
  }

  return {
    get(url) {
      if (!url) return null;
      const existing = store.get(url);
      if (existing) {
        // Promote: delete + re-insert moves it to the newest slot.
        store.delete(url);
        store.set(url, existing);
        return existing;
      }
      const img = load(url);
      store.set(url, img);
      evictIfNeeded();
      return img;
    },
    peek(url) {
      if (!url) return null;
      return store.get(url) ?? null;
    },
    has(url) {
      return store.has(url);
    },
    get size() {
      return store.size;
    },
  };
}
