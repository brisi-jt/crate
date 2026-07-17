"use client";

import { domToBlob } from "modern-screenshot";
import { CARD_HEIGHT, CARD_WIDTH } from "./card-view";

/**
 * Render an off-screen card node to a PNG blob at the fixed story size. The
 * node is laid out at 1080×1350 off-screen; modern-screenshot rasterizes it
 * (album art is cross-origin-anonymous already, so the canvas never taints).
 */
export async function cardToBlob(node: HTMLElement): Promise<Blob> {
  return domToBlob(node, {
    width: CARD_WIDTH,
    height: CARD_HEIGHT,
    // Rasterize at the node's own pixel size — it's already 1080×1350.
    scale: 1,
    // Skip web-font embedding: the card uses system-safe stacks, and font
    // embedding over the network can hang or fail in an off-screen render.
    font: false,
  });
}

/** Trigger a browser download of a blob under a filename. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick so the download has grabbed the URL.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Copy a blob to the clipboard where the API + permissions allow it. */
export async function copyBlobToClipboard(blob: Blob): Promise<boolean> {
  try {
    if (!navigator.clipboard || typeof ClipboardItem === "undefined") {
      return false;
    }
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
    return true;
  } catch {
    return false;
  }
}
