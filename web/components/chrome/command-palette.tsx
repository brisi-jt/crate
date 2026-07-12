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
import { useTriggerSync } from "@/hooks/api/use-sync";
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
  const setMapMode = useUiStore((s) => s.setMapMode);
  const openBulkOps = useUiStore((s) => s.openBulkOps);
  const openOpsLog = useUiStore((s) => s.openOpsLog);
  const closeRightPanel = useUiStore((s) => s.closeRightPanel);
  const rightPanel = useUiStore((s) => s.rightPanel);
  const selectedPlaylistId = useUiStore((s) => s.selectedPlaylistId);
  const sync = useTriggerSync();

  if (!paletteOpen) return null;

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
                onSelect={() => openPlaylist(node.id)}
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
          <CommandSeparator className="bg-border-subtle" />
          <CommandGroup
            heading="Panels"
            className="[&_[cmdk-group-heading]]:micro-caps [&_[cmdk-group-heading]]:text-text-muted"
          >
            <CommandItem
              onSelect={() => openInsights()}
              className="data-[selected=true]:bg-surface-2"
            >
              Open insights
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
