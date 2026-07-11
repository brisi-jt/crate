"use client";

import { NotYetComputed, Readout } from "@/components/panels/right-dock";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLibraryStats } from "@/hooks/api/use-library-stats";
import type { LibraryStats } from "@/lib/api/schemas";

export function LibraryStatsPanelContent() {
  const stats = useLibraryStats(true);

  if (stats.isPending) {
    return (
      <div className="flex flex-col gap-sm">
        <Skeleton className="h-16 w-full bg-surface-2" />
        <Skeleton className="h-40 w-full bg-surface-2" />
      </div>
    );
  }

  if (stats.isError) {
    return (
      <p className="text-sm text-text-secondary">
        Couldn't load library stats —{" "}
        <button
          type="button"
          className="cursor-pointer underline"
          onClick={() => stats.refetch()}
        >
          retry
        </button>
        .
      </p>
    );
  }

  const data = stats.data ?? null;

  return (
    <Tabs defaultValue="drift" className="flex min-h-0 flex-1 flex-col gap-lg">
      <TabsList className="w-full justify-start gap-lg rounded-none border-border-subtle border-b bg-transparent p-0">
        {["drift", "clusters", "duplicates"].map((tab) => (
          <TabsTrigger
            key={tab}
            value={tab}
            className="micro-caps rounded-none border-0 border-transparent border-b-2 bg-transparent px-0 pb-xs text-text-muted shadow-none data-[state=active]:border-text-primary data-[state=active]:bg-transparent data-[state=active]:text-text-primary data-[state=active]:shadow-none"
          >
            {tab}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value="drift">
        {data && data.drift.length > 0 ? (
          <DriftChart drift={data.drift} />
        ) : (
          <NotYetComputed what="Temporal drift" />
        )}
      </TabsContent>

      <TabsContent value="clusters">
        {data?.clusters ? (
          <div className="flex gap-xl">
            <Readout label="ARI" value={data.clusters.ari.toFixed(2)} />
            <Readout
              label="Clusters"
              value={String(data.clusters.cluster_count)}
            />
            <Readout
              label="Split hints"
              value={String(data.clusters.split_suggestions)}
            />
            <Readout
              label="Merge hints"
              value={String(data.clusters.merge_suggestions)}
            />
          </div>
        ) : (
          <NotYetComputed what="Clusters vs playlists" />
        )}
      </TabsContent>

      <TabsContent value="duplicates">
        {data ? (
          data.duplicates.length === 0 ? (
            <p className="text-sm text-text-secondary">
              No cross-library duplicates found.
            </p>
          ) : (
            <ul className="flex flex-col">
              {data.duplicates.map((duplicate) => (
                <li
                  key={`${duplicate.isrc}-${duplicate.name}`}
                  className="flex items-baseline gap-sm border-border-subtle border-b py-xs text-sm"
                >
                  <span className="text-text-primary">{duplicate.name}</span>
                  <span className="text-text-secondary">
                    {duplicate.artist}
                  </span>
                  <span className="data-readout ml-auto text-micro text-text-muted">
                    {duplicate.playlists.join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : (
          <NotYetComputed what="Duplicates report" />
        )}
      </TabsContent>
    </Tabs>
  );
}

/**
 * Temporal drift as a labeled SVG line chart — real axes and ticks, no
 * sparkline decoration (charts are data).
 */
function DriftChart({ drift }: { drift: LibraryStats["drift"] }) {
  const width = 560;
  const height = 200;
  const pad = { left: 36, right: 12, top: 12, bottom: 24 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const series: Array<{
    key: "energy" | "valence" | "acousticness";
    label: string;
  }> = [
    { key: "energy", label: "ENERGY" },
    { key: "valence", label: "VALENCE" },
    { key: "acousticness", label: "ACOUSTIC" },
  ];
  const dashes = ["", "4 3", "1 3"];

  const x = (i: number) =>
    pad.left + (drift.length === 1 ? 0 : (i / (drift.length - 1)) * innerW);
  const y = (v: number) => pad.top + (1 - v) * innerH;

  return (
    <figure className="flex flex-col gap-xs">
      <figcaption className="micro-caps text-text-muted">
        Add-centroid drift by quarter (library percentile)
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Temporal drift chart"
        className="w-full"
      >
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--border-subtle)"
            />
            <text
              x={pad.left - 6}
              y={y(tick) + 3}
              textAnchor="end"
              className="fill-text-muted font-[family-name:var(--font-b612-mono)] text-[10px]"
            >
              P{Math.round(tick * 100)}
            </text>
          </g>
        ))}
        {series.map(({ key, label }, si) => (
          <g key={key}>
            <polyline
              fill="none"
              stroke="var(--text-secondary)"
              strokeWidth={1.25}
              strokeDasharray={dashes[si]}
              points={drift.map((d, i) => `${x(i)},${y(d[key])}`).join(" ")}
            />
            <text
              x={x(drift.length - 1) + 4}
              y={y(drift[drift.length - 1][key])}
              className="fill-text-muted font-[family-name:var(--font-b612-mono)] text-[9px]"
            >
              {label}
            </text>
          </g>
        ))}
        {drift.map((d, i) => (
          <text
            key={d.quarter}
            x={x(i)}
            y={height - 6}
            textAnchor="middle"
            className="fill-text-muted font-[family-name:var(--font-b612-mono)] text-[10px]"
          >
            {d.quarter}
          </text>
        ))}
      </svg>
    </figure>
  );
}
