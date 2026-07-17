"use client";

import { useEffect, useRef, useState } from "react";
import { hoverImageCache } from "@/lib/canvas/dom-image-loader";
import type {
  ArtistCardModel,
  FingerprintBar,
  TrackCardModel,
} from "@/lib/canvas/hover-card";
import { clampCardPosition } from "@/lib/canvas/hover-card";
import { type Oklch, oklchString } from "@/lib/color/acoustic";

/**
 * The shared rich hover-card shell. A DOM overlay positioned over the
 * canvas (never canvas-drawn — image decode + text layout on the 2D context
 * during pan would tank frame rate). The card is tinted by the node's own
 * acoustic colour (synesthesia: the card is literally the sound's colour) with
 * that colour as a left rail. A 64px art thumb cross-fades in from a colour
 * placeholder; imagery is served from the shared LRU cache.
 */

const CARD_WIDTH = 264;
const CARD_HEIGHT = 132;
const THUMB = 64;

interface Shell {
  /** Node's acoustic colour — tints the card + rail. */
  color: Oklch;
  /** Cursor position in container-local px. */
  x: number;
  y: number;
  containerWidth: number;
  containerHeight: number;
  rightInset: number;
}

interface TrackHoverCardProps extends Shell {
  model: TrackCardModel;
}

interface ArtistHoverCardProps extends Shell {
  model: ArtistCardModel;
}

interface PlaylistHoverCardProps extends Shell {
  title: string;
  trackCount: number;
  /** Up to four member-album thumbs — a 2×2 mosaic cover. */
  mosaicUrls: string[];
  clusterLabel: string | null;
  topPartner: string | null;
}

interface GenreHoverCardProps extends Shell {
  title: string;
  /** ENAO rank readout (rarity). */
  enaoRank: number | null;
  exemplars: string[];
}

function CardFrame({
  color,
  x,
  y,
  containerWidth,
  containerHeight,
  rightInset,
  children,
}: Shell & { children: React.ReactNode }) {
  const pos = clampCardPosition(
    x,
    y,
    { width: CARD_WIDTH, height: CARD_HEIGHT },
    { width: containerWidth, height: containerHeight, rightInset },
  );
  const tint = oklchString({ l: 0.18, c: Math.min(color.c, 0.05), h: color.h });
  return (
    <div
      className="pointer-events-none absolute z-20 flex gap-sm overflow-hidden rounded-md border border-border-subtle py-sm pr-md pl-0 shadow-sm"
      style={{
        left: pos.left,
        top: pos.top,
        width: CARD_WIDTH,
        // Node colour washed into the surface — the card is the sound's colour.
        background: `linear-gradient(135deg, ${tint}, var(--surface-2))`,
      }}
    >
      {/* 3px left rail in the node's own colour. */}
      <div
        className="w-[3px] flex-none self-stretch"
        style={{ background: oklchString(color) }}
      />
      {children}
    </div>
  );
}

/** A 64px thumb that cross-fades from the node colour placeholder to the art. */
export function Thumb({
  url,
  color,
  rounded = "rounded-sm",
}: {
  url: string | null;
  color: Oklch;
  rounded?: string;
}) {
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    setLoaded(false);
    if (!url) return;
    const el = hoverImageCache().get(url);
    imgRef.current = el;
    if (!el) return;
    if (el.complete && el.naturalWidth > 0) {
      setLoaded(true);
      return;
    }
    const onLoad = () => setLoaded(true);
    el.addEventListener("load", onLoad);
    return () => el.removeEventListener("load", onLoad);
  }, [url]);

  return (
    <div
      className={`relative flex-none overflow-hidden ${rounded}`}
      style={{
        width: THUMB,
        height: THUMB,
        background: oklchString(color),
      }}
    >
      {url && (
        // biome-ignore lint/performance/noImgElement: canvas-overlay thumb, LRU-cached, not a page image
        <img
          src={url}
          alt=""
          width={THUMB}
          height={THUMB}
          className="size-full object-cover transition-opacity duration-200"
          style={{ opacity: loaded ? 1 : 0 }}
          onLoad={() => setLoaded(true)}
        />
      )}
    </div>
  );
}

function Fingerprint({ bars }: { bars: FingerprintBar[] }) {
  return (
    <div className="flex gap-sm">
      {bars.map((b) => (
        <span key={b.label} className="flex items-baseline gap-2xs">
          <span className="micro-caps text-text-muted">{b.label}</span>
          <span className="data-readout text-micro text-text-secondary">
            {b.value.toFixed(2)}
          </span>
        </span>
      ))}
    </div>
  );
}

export function TrackHoverCard({
  model,
  color,
  ...shell
}: TrackHoverCardProps) {
  return (
    <CardFrame color={color} {...shell}>
      <Thumb url={model.imageUrl} color={color} />
      <div className="flex min-w-0 flex-col justify-center gap-2xs">
        <span className="truncate font-bold text-sm text-text-primary">
          {model.title}
        </span>
        <span className="truncate text-micro text-text-secondary">
          {model.subtitle}
        </span>
        {model.fingerprint && <Fingerprint bars={model.fingerprint} />}
        <div className="flex gap-sm">
          {model.clusterId !== null && (
            <span className="data-readout text-micro text-text-muted">
              C{model.clusterId}
            </span>
          )}
          <span className="data-readout text-micro text-text-muted">
            {model.playlistCount} PL
          </span>
        </div>
      </div>
    </CardFrame>
  );
}

export function ArtistHoverCard({
  model,
  color,
  ...shell
}: ArtistHoverCardProps) {
  return (
    <CardFrame color={color} {...shell}>
      <Thumb url={model.imageUrl} color={color} rounded="rounded-full" />
      <div className="flex min-w-0 flex-col justify-center gap-2xs">
        <span className="truncate font-bold text-sm text-text-primary">
          {model.title}
        </span>
        <span className="data-readout text-micro text-text-muted">
          {model.trackCount} TRK · {model.playlistCount} PL
        </span>
        {model.genres.length > 0 && (
          <span className="truncate text-micro text-text-secondary">
            {model.genres.join(" · ")}
          </span>
        )}
        {model.similar.length > 0 && (
          <span className="truncate text-micro text-text-muted">
            ~{" "}
            {model.similar
              .map((s) => (s.inLibrary ? `${s.name}•` : s.name))
              .join(", ")}
          </span>
        )}
      </div>
    </CardFrame>
  );
}

export function PlaylistHoverCard({
  title,
  trackCount,
  mosaicUrls,
  clusterLabel,
  topPartner,
  color,
  ...shell
}: PlaylistHoverCardProps) {
  const tiles = mosaicUrls.slice(0, 4);
  return (
    <CardFrame color={color} {...shell}>
      {/* 2×2 album mosaic built from member albums — more truthful than a cover. */}
      <div
        className="grid flex-none grid-cols-2 grid-rows-2 gap-[1px] overflow-hidden rounded-sm"
        style={{ width: THUMB, height: THUMB, background: oklchString(color) }}
      >
        {[0, 1, 2, 3].map((i) => (
          <Thumb
            key={i}
            url={tiles[i] ?? null}
            color={color}
            rounded="rounded-none"
          />
        ))}
      </div>
      <div className="flex min-w-0 flex-col justify-center gap-2xs">
        <span className="truncate font-bold text-sm text-text-primary">
          {title}
        </span>
        <span className="data-readout text-micro text-text-muted">
          {trackCount} TRACKS
        </span>
        {clusterLabel && (
          <span className="truncate text-micro text-text-secondary">
            {clusterLabel}
          </span>
        )}
        {topPartner && (
          <span className="truncate text-micro text-text-muted">
            ↔ {topPartner}
          </span>
        )}
      </div>
    </CardFrame>
  );
}

export function GenreHoverCard({
  title,
  enaoRank,
  exemplars,
  color,
  ...shell
}: GenreHoverCardProps) {
  return (
    <CardFrame color={color} {...shell}>
      {/* No natural image — the genre's acoustic centroid colour is the anchor. */}
      <div
        className="flex-none rounded-sm"
        style={{ width: THUMB, height: THUMB, background: oklchString(color) }}
      />
      <div className="flex min-w-0 flex-col justify-center gap-2xs">
        <span className="truncate font-bold text-sm text-text-primary">
          {title}
        </span>
        {enaoRank !== null && (
          <span className="data-readout text-micro text-text-muted">
            ENAO #{enaoRank}
          </span>
        )}
        {exemplars.length > 0 && (
          <span className="truncate text-micro text-text-secondary">
            {exemplars.join(", ")}
          </span>
        )}
      </div>
    </CardFrame>
  );
}

export const HOVER_CARD_WIDTH = CARD_WIDTH;
export const HOVER_CARD_HEIGHT = CARD_HEIGHT;
