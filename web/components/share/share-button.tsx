"use client";

import { Download } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { toast } from "sonner";
import { ShareCardFrame } from "@/components/share/share-card-frame";
import { Button } from "@/components/ui/button";
import { shareFilename } from "@/lib/share/card-view";
import {
  cardToBlob,
  copyBlobToClipboard,
  downloadBlob,
} from "@/lib/share/export";

/**
 * A one-tap "export this as a share image" affordance (S2). Renders the given
 * card body inside the off-screen 1080×1350 frame, rasterizes it to a PNG,
 * downloads it, and (best-effort) copies it to the clipboard.
 *
 * The frame is always mounted but pushed far off-screen so it's laid out for a
 * faithful capture without ever being visible.
 */
export function ShareButton({
  kind,
  title,
  subtitle,
  children,
  label = "Share image",
}: {
  /** Filename tag + card title, e.g. "dna" / "Listening clock". */
  kind: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  label?: string;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);

  async function handleExport() {
    if (!frameRef.current || busy) return;
    setBusy(true);
    try {
      const blob = await cardToBlob(frameRef.current);
      downloadBlob(blob, shareFilename(kind));
      const copied = await copyBlobToClipboard(blob);
      toast(copied ? "Image saved and copied to clipboard" : "Image saved");
    } catch (error) {
      toast.error(
        error instanceof Error
          ? `Export failed — ${error.message}`
          : "Export failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        onClick={handleExport}
        disabled={busy}
        className="micro-caps gap-xs border-border-subtle text-text-secondary"
      >
        <Download className="size-[13px]" />
        {busy ? "Exporting…" : label}
      </Button>

      {/* Off-screen render target — laid out at full size, never visible. */}
      <div
        aria-hidden
        style={{
          position: "fixed",
          left: -20000,
          top: 0,
          pointerEvents: "none",
        }}
      >
        <ShareCardFrame ref={frameRef} title={title} subtitle={subtitle}>
          {children}
        </ShareCardFrame>
      </div>
    </>
  );
}
