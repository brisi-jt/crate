"use client";

/**
 * G1 — the browser image loader for the hover-card LRU cache. Kicks off a
 * decode for a url and returns the element immediately (the card cross-fades
 * from a colour placeholder to the image on load). Separated from the cache so
 * the cache stays DOM-free and unit-testable.
 */

import { createImageCache, type ImageCache } from "./image-cache";

function domLoad(url: string): HTMLImageElement {
  const img = new Image();
  // Album/artist art is served cross-origin; anonymous lets it paint without
  // tainting (share-card export in Phase 6 needs untainted canvases too).
  img.crossOrigin = "anonymous";
  img.decoding = "async";
  img.src = url;
  return img;
}

/** A single shared hover-card image cache for the whole session (≤200 thumbs). */
let shared: ImageCache | null = null;

export function hoverImageCache(): ImageCache {
  if (!shared) shared = createImageCache({ load: domLoad });
  return shared;
}
