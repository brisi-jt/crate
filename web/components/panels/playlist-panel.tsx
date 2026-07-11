"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";
import { NotYetComputed, Readout } from "@/components/panels/right-dock";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePlaylistAnalytics } from "@/hooks/api/use-playlist-analytics";
import {
  TRACK_PAGE_SIZE,
  usePlaylistTracks,
} from "@/hooks/api/use-playlist-tracks";
import type { GraphNode, PlaylistTrack } from "@/lib/api/schemas";

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

const columnHelper = createColumnHelper<PlaylistTrack>();

const trackColumns = [
  columnHelper.accessor("position", {
    header: "#",
    cell: (info) => String(info.getValue() + 1).padStart(2, "0"),
  }),
  columnHelper.accessor("track.name", {
    header: "Title",
    cell: (info) => (
      <span>
        <span className="text-text-primary">{info.getValue()}</span>
        <span className="text-text-secondary">
          {" · "}
          {info.row.original.track.artists.map((a) => a.name).join(", ")}
        </span>
      </span>
    ),
  }),
  columnHelper.accessor("track.duration_ms", {
    header: "Dur",
    cell: (info) => formatDuration(info.getValue()),
  }),
];

interface PlaylistPanelContentProps {
  playlistId: number;
  node: GraphNode | null;
  /** The playlist's acoustic color — fills the fingerprint bars. */
  swatch: string | null;
}

export function PlaylistPanelContent({
  playlistId,
  node,
  swatch,
}: PlaylistPanelContentProps) {
  const [offset, setOffset] = useState(0);
  const tracks = usePlaylistTracks(playlistId, offset);
  const analytics = usePlaylistAnalytics(playlistId);

  const table = useReactTable({
    data: tracks.data?.items ?? [],
    columns: trackColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  const total = tracks.data?.total ?? node?.track_count ?? 0;
  const a = analytics.data ?? null;

  return (
    <>
      <div className="flex gap-xl">
        <Readout label="Tracks" value={String(total)} />
        <Readout
          label="Cohesion"
          value={a?.cohesion != null ? a.cohesion.toFixed(2) : "—"}
        />
        <Readout
          label="Flow"
          value={a?.flow ? String(Math.round(a.flow.score)) : "—"}
        />
        <Readout label="Outliers" value={a ? String(a.outliers.length) : "—"} />
      </div>

      <Tabs defaultValue="tracks" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="w-full justify-start gap-lg rounded-none border-border-subtle border-b bg-transparent p-0">
          {["tracks", "fingerprint", "overlaps", "outliers"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="micro-caps rounded-none border-0 border-transparent border-b-2 bg-transparent px-0 pb-xs text-text-muted shadow-none data-[state=active]:border-text-primary data-[state=active]:bg-transparent data-[state=active]:text-text-primary data-[state=active]:shadow-none"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="tracks" className="flex flex-col gap-sm pt-sm">
          {tracks.isPending && (
            <div className="flex flex-col gap-xs">
              {Array.from({ length: 8 }, (_, i) => `track-skeleton-${i}`).map(
                (key) => (
                  <Skeleton key={key} className="h-8 w-full bg-surface-2" />
                ),
              )}
            </div>
          )}
          {tracks.isError && (
            <p className="text-sm text-text-secondary">
              Couldn't load tracks —{" "}
              <button
                type="button"
                className="cursor-pointer underline"
                onClick={() => tracks.refetch()}
              >
                retry
              </button>
              .
            </p>
          )}
          {tracks.data && tracks.data.items.length === 0 && (
            <p className="text-sm text-text-secondary">
              No tracks synced for this playlist yet.
            </p>
          )}
          {tracks.data && tracks.data.items.length > 0 && (
            <>
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <TableRow
                      key={headerGroup.id}
                      className="border-border-strong hover:bg-transparent"
                    >
                      {headerGroup.headers.map((header) => (
                        <TableHead
                          key={header.id}
                          className="micro-caps h-8 text-text-muted last:text-right"
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                        </TableHead>
                      ))}
                    </TableRow>
                  ))}
                </TableHeader>
                <TableBody>
                  {table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="border-border-subtle text-sm hover:bg-surface-2"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className="data-readout py-xs text-text-secondary first:w-8 last:text-right [&:nth-child(2)]:font-[family-name:var(--font-b612)]"
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center gap-sm">
                <span className="data-readout text-micro text-text-muted">
                  {offset + 1}–{Math.min(offset + TRACK_PAGE_SIZE, total)} of{" "}
                  {total}
                </span>
                <div className="ml-auto flex gap-xs">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={offset === 0}
                    onClick={() =>
                      setOffset(Math.max(0, offset - TRACK_PAGE_SIZE))
                    }
                  >
                    Prev
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={offset + TRACK_PAGE_SIZE >= total}
                    onClick={() => setOffset(offset + TRACK_PAGE_SIZE)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="fingerprint" className="pt-sm">
          {a?.fingerprint ? (
            <div className="flex flex-col gap-xs">
              <span className="micro-caps text-text-muted">
                Fingerprint · vs library median (tick)
              </span>
              {a.fingerprint.map(({ feature, percentile }) => (
                <div
                  key={feature}
                  className="grid grid-cols-[110px_1fr_42px] items-center gap-sm"
                >
                  <span className="micro-caps text-text-muted">{feature}</span>
                  <div className="relative h-[6px] rounded-xs bg-surface-2">
                    <div
                      className="h-[6px] rounded-xs"
                      style={{
                        width: `${Math.round(percentile * 100)}%`,
                        background: swatch ?? "var(--text-secondary)",
                      }}
                    />
                    <div className="absolute top-[-3px] left-1/2 h-[12px] w-[2px] bg-text-secondary" />
                  </div>
                  <span className="data-readout text-right text-micro text-text-secondary">
                    P{Math.round(percentile * 100)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <NotYetComputed what="Feature fingerprint" />
          )}
        </TabsContent>

        <TabsContent value="overlaps" className="pt-sm">
          {a ? (
            a.overlaps.length === 0 ? (
              <p className="text-sm text-text-secondary">
                No overlap with any other playlist.
              </p>
            ) : (
              <ul className="flex flex-col">
                {a.overlaps.map((overlap) => (
                  <li
                    key={overlap.playlist_id}
                    className="flex items-center gap-sm border-border-subtle border-b py-xs text-sm"
                  >
                    <span className="text-text-primary">{overlap.name}</span>
                    <span className="data-readout ml-auto rounded-xs border border-border-subtle px-xs text-micro text-text-secondary">
                      {overlap.shared} shared
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <NotYetComputed what="Overlap partners" />
          )}
        </TabsContent>

        <TabsContent value="outliers" className="pt-sm">
          {a ? (
            a.outliers.length === 0 ? (
              <p className="text-sm text-text-secondary">
                No outliers — this playlist is tight.
              </p>
            ) : (
              <ul className="flex flex-col">
                {a.outliers.map((outlier) => (
                  <li
                    key={outlier.track_id}
                    className="flex items-center gap-sm border-border-subtle border-b py-xs text-sm"
                  >
                    <span className="text-text-primary">{outlier.name}</span>
                    <span className="text-text-secondary">
                      {outlier.artist}
                    </span>
                    <span className="data-readout ml-auto text-micro text-text-muted">
                      d {outlier.distance.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <NotYetComputed what="Outliers" />
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}
