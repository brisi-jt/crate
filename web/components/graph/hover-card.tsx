"use client";

import { Thumb } from "@/components/canvas/rich-hover-card";
import type { GraphEdge, GraphNode } from "@/lib/api/schemas";
import { GREY_NODE, oklchString } from "@/lib/color/acoustic";
import { type Equalizer, equalizedColor } from "@/lib/color/equalize";

interface GraphHoverCardProps {
  node: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
  x: number;
  y: number;
  containerWidth: number;
  /** Library equalizer so the swatch matches the equalized node fill (G4). */
  equalizer: Equalizer | null;
}

/**
 * Canvas nodes can't anchor a DOM HoverCard, so this is a manually positioned
 * readout on --surface-2 (component inventory §3.1). G1: the playlist cover
 * (when Spotify has one) anchors the card, tinted by the playlist's own
 * acoustic colour; the overlap/subset readouts stay.
 */
export function GraphHoverCard({
  node,
  nodes,
  edges,
  x,
  y,
  containerWidth,
  equalizer,
}: GraphHoverCardProps) {
  const nameById = new Map(nodes.map((n) => [n.id, n.name]));

  const incident = edges
    .filter((e) => e.source === node.id || e.target === node.id)
    .sort((a, b) => b.shared - a.shared);
  const top = incident[0];
  const topPartner = top
    ? nameById.get(top.source === node.id ? top.target : top.source)
    : null;

  const subsetOf = edges.find((e) => e.subset && e.source === node.id);
  const subsetParent = subsetOf ? nameById.get(subsetOf.target) : null;

  const color =
    node.centroid && equalizer
      ? equalizedColor(node.centroid, equalizer)
      : GREY_NODE;

  const cardWidth = 264;
  const left = Math.min(x + 18, containerWidth - cardWidth - 12);

  return (
    <div
      className="pointer-events-none absolute z-10 flex gap-sm rounded-md border border-border-subtle bg-surface-2 px-md py-sm"
      style={{ left, top: y + 18, width: cardWidth }}
    >
      <Thumb url={node.image_url ?? null} color={color} />
      <div className="flex min-w-0 flex-1 flex-col gap-2xs">
        <div className="flex items-center gap-xs font-bold text-sm text-text-primary">
          <span
            className="inline-block size-[10px] flex-none rounded-xs"
            style={{ background: oklchString(color) }}
          />
          <span className="truncate">{node.name}</span>
        </div>
        <Row label="tracks" value={String(node.track_count)} />
        {node.centroid === null ? (
          <Row label="features" value={`0/${node.track_count}`} />
        ) : (
          <Row
            label="top overlap"
            value={topPartner ? `${topPartner} · ${top?.shared}` : "—"}
          />
        )}
        {subsetParent && (
          <Row
            label="subset of"
            value={`${subsetParent} · ${subsetOf?.shared}/${node.track_count}`}
          />
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-sm text-text-secondary">
      <span>{label}</span>
      <span className="data-readout truncate pl-sm text-text-primary">
        {value}
      </span>
    </div>
  );
}
