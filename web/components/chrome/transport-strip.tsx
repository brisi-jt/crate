"use client";

import { Button } from "@/components/ui/button";

/**
 * The always-present transport strip (56px, bottom). Playback wiring is the
 * discovery phase's — until then the controls are disabled and the strip
 * offers the connect affordance. Nothing may overlap this strip.
 */
export function TransportStrip() {
  return (
    <footer className="absolute right-0 bottom-0 left-0 z-30 flex h-[56px] items-center gap-md border-border-subtle border-t bg-surface-1 px-md">
      <div className="size-8 rounded-xs border border-border-subtle bg-surface-2" />
      <div className="flex w-[210px] flex-col leading-tight">
        <span className="text-sm text-text-secondary">Nothing playing</span>
        <span className="micro-caps text-text-muted">NO DEVICE</span>
      </div>
      <div className="flex items-center gap-2xs">
        <TransportButton label="Previous track">⏮</TransportButton>
        <TransportButton label="Play">▶</TransportButton>
        <TransportButton label="Next track">⏭</TransportButton>
      </div>
      <div className="flex flex-1 items-center gap-sm">
        <span className="data-readout text-micro text-text-muted">0:00</span>
        <div className="h-[3px] flex-1 rounded-full bg-surface-3" />
        <span className="data-readout text-micro text-text-muted">0:00</span>
      </div>
      <div className="h-[3px] w-[90px] rounded-full bg-surface-3" />
      <Button
        variant="ghost"
        size="sm"
        disabled
        className="micro-caps text-text-muted"
        title="Web Playback SDK arrives with the discovery deck"
      >
        Connect Spotify playback
      </Button>
    </footer>
  );
}

function TransportButton({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled
      aria-label={label}
      className="rounded-xs px-xs py-2xs text-[15px] text-text-muted"
    >
      {children}
    </button>
  );
}
