"use client";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useArtistGalaxy } from "@/hooks/api/use-artist-galaxy";
import { useTriggerSync } from "@/hooks/api/use-sync";
import { useTrackMap } from "@/hooks/api/use-track-map";
import type { GraphNode } from "@/lib/api/schemas";
import { acousticColor, GREY_NODE, oklchString } from "@/lib/color/acoustic";
import { openListeningDeck } from "@/lib/store/deck";
import { useUiStore } from "@/lib/store/ui";

/**
 * ⌘K palette: a positioned dock on --surface-3, center-top — the one
 * floating layer. Deliberately NOT the shadcn CommandDialog (modal semantics
 * are banned; the map stays visible and live underneath).
 */
export function CommandPalette({ nodes }: { nodes: GraphNode[] }) {
  const paletteOpen = useUiStore((s) => s.paletteOpen);
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);
  const openPlaylist = useUiStore((s) => s.openPlaylist);
  const openStats = useUiStore((s) => s.openStats);
  const openFrontier = useUiStore((s) => s.openFrontier);
  const openInbox = useUiStore((s) => s.openInbox);
  const openRadio = useUiStore((s) => s.openRadio);
  const openInsights = useUiStore((s) => s.openInsights);
  const openTriage = useUiStore((s) => s.openTriage);
  const openDashboard = useUiStore((s) => s.openDashboard);
  const setMapMode = useUiStore((s) => s.setMapMode);
  const openBulkOps = useUiStore((s) => s.openBulkOps);
  const openOpsLog = useUiStore((s) => s.openOpsLog);
  const openGlossary = useUiStore((s) => s.openGlossary);
  const flyToNode = useUiStore((s) => s.flyToNode);
  const closeRightPanel = useUiStore((s) => s.closeRightPanel);
  const rightPanel = useUiStore((s) => s.rightPanel);
  const selectedPlaylistId = useUiStore((s) => s.selectedPlaylistId);
  const sync = useTriggerSync();

  // Search-to-focus (G5) targets: tracks + artists. Only fetched while the
  // palette is open (the queries are already cached by the map views).
  const trackMap = useTrackMap();
  const galaxy = useArtistGalaxy();

  if (!paletteOpen) return null;

  const tracks = trackMap.data?.points ?? [];
  const artists = galaxy.data?.nodes ?? [];

  return (
    <div className="-translate-x-1/2 absolute top-[64px] left-1/2 z-40 w-[560px]">
      <Command className="rounded-md border border-border-subtle bg-surface-3 text-text-primary">
        <CommandInput
          autoFocus
          placeholder="Jump to a playlist, open a panel, run a sync…"
          className="text-text-primary placeholder:text-text-muted"
        />
        <CommandList>
          <CommandEmpty className="py-lg text-center text-sm text-text-muted">
            Nothing matches.
          </CommandEmpty>
          <CommandGroup
            heading="Playlists"
            className="[&_[cmdk-group-heading]]:micro-caps [&_[cmdk-group-heading]]:text-text-muted"
          >
            {nodes.map((node) => (
              <CommandItem
                key={node.id}
                value={node.name}
                onSelect={() => {
                  flyToNode("playlists", node.id);
                  openPlaylist(node.id);
                }}
                className="gap-sm data-[selected=true]:bg-surface-2"
              >
                <span
                  className="inline-block size-[10px] rounded-xs"
                  style={{
                    background: oklchString(
                      node.centroid ? acousticColor(node.centroid) : GREY_NODE,
                    ),
                  }}
                />
                {node.name}
                <span className="data-readout ml-auto text-micro text-text-muted">
                  {node.track_count}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
          {artists.length > 0 && (
            <>
              <CommandSeparator className="bg-border-subtle" />
              <CommandGroup
                heading="Artists"
                className="[&_[cmdk-group-heading]]:micro-caps [&_[cmdk-group-heading]]:text-text-muted"
              >
                {artists.slice(0, 400).map((a) => (
                  <CommandItem
                    key={a.id}
                    value={`artist ${a.name}`}
                    onSelect={() => flyToNode("artists", a.id)}
                    className="gap-sm data-[selected=true]:bg-surface-2"
                  >
                    {a.name}
                    <span className="data-readout ml-auto text-micro text-text-muted">
                      {a.track_count}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
          {tracks.length > 0 && (
            <>
              <CommandSeparator className="bg-border-subtle" />
              <CommandGroup
                heading="Tracks"
                className="[&_[cmdk-group-heading]]:micro-caps [&_[cmdk-group-heading]]:text-text-muted"
              >
                {tracks.slice(0, 400).map((t) => (
                  <CommandItem
                    key={t.track_id}
                    value={`track ${t.name} ${t.artist}`}
                    onSelect={() => flyToNode("tracks", t.track_id)}
                    className="gap-sm data-[selected=true]:bg-surface-2"
                  >
                    <span className="truncate">{t.name}</span>
                    <span className="ml-auto truncate text-micro text-text-muted">
                      {t.artist}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
          <CommandSeparator className="bg-border-subtle" />
          <CommandGroup
            heading="Panels"
            className="[&_[cmdk-group-heading]]:micro-caps [&_[cmdk-group-heading]]:text-text-muted"
          >
            <CommandItem
              onSelect={() => openTriage()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open triage
            </CommandItem>
            <CommandItem
              onSelect={() => openInsights()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open insights
            </CommandItem>
            <CommandItem
              value="dashboard listening obscurity taste drift crate dna share"
              onSelect={() => openDashboard()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open dashboard
            </CommandItem>
            <CommandItem
              onSelect={() => openStats()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open library stats
            </CommandItem>
            <CommandItem
              onSelect={() => openBulkOps()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open bulk operations
            </CommandItem>
            <CommandItem
              onSelect={() => openOpsLog()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open operations log
            </CommandItem>
            <CommandItem
              onSelect={() => openFrontier()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open frontier explorer
            </CommandItem>
            <CommandItem
              onSelect={() => openInbox()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open inbox
            </CommandItem>
            <CommandItem
              onSelect={() => openRadio()}
              className="data-[selected=true]:bg-surface-2"
            >
              Start a radio
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setMapMode("artists");
                setPaletteOpen(false);
              }}
              className="data-[selected=true]:bg-surface-2"
            >
              View artist galaxy
            </CommandItem>
            {selectedPlaylistId !== null && (
              <CommandItem
                onSelect={() => openListeningDeck(selectedPlaylistId)}
                className="data-[selected=true]:bg-surface-2"
              >
                Audition suggestions
              </CommandItem>
            )}
            {rightPanel && (
              <CommandItem
                onSelect={() => {
                  closeRightPanel();
                  setPaletteOpen(false);
                }}
                className="data-[selected=true]:bg-surface-2"
              >
                Close panel
              </CommandItem>
            )}
          </CommandGroup>
          <CommandSeparator className="bg-border-subtle" />
          <CommandGroup
            heading="Actions"
            className="[&_[cmdk-group-heading]]:micro-caps [&_[cmdk-group-heading]]:text-text-muted"
          >
            <CommandItem
              value="glossary explain what is this"
              onSelect={() => openGlossary()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open glossary
            </CommandItem>
            <CommandItem
              onSelect={() => {
                sync.mutate();
                setPaletteOpen(false);
              }}
              className="data-[selected=true]:bg-surface-2"
            >
              Sync now
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
}
