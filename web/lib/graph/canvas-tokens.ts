/**
 * Design-token colors the canvas painters need, resolved from CSS once per
 * mount. Shared by the playlist-graph and track-field renderers so both maps
 * read the same instrument palette.
 */

export interface CanvasTokens {
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  borderSubtle: string;
  borderStrong: string;
  surface1: string;
  fontText: string;
  fontData: string;
  canvas: string;
}

export function readCanvasTokens(): CanvasTokens {
  const style = getComputedStyle(document.documentElement);
  const v = (name: string) => style.getPropertyValue(name).trim();
  return {
    textPrimary: v("--text-primary"),
    textSecondary: v("--text-secondary"),
    textMuted: v("--text-muted"),
    borderSubtle: v("--border-subtle"),
    borderStrong: v("--border-strong"),
    surface1: v("--surface-1") || "oklch(0.16 0.016 265)",
    fontText: v("--font-b612") || "sans-serif",
    fontData: v("--font-b612-mono") || "monospace",
    canvas: v("--canvas") || "oklch(0.13 0.015 265)",
  };
}
