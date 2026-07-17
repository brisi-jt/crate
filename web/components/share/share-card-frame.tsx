"use client";

import { forwardRef, type ReactNode } from "react";
import { CARD_HEIGHT, CARD_WIDTH, legendFooter } from "@/lib/share/card-view";

/**
 * The fixed 1080×1350 story-format card shell (S2). Rendered off-screen and
 * rasterized to a blob. Field-manual aesthetic: dark canvas, Michroma wordmark,
 * a body slot, and a self-contained OKLCH legend footer so a shared image
 * carries its own colour key. Never shown on screen directly.
 */
export const ShareCardFrame = forwardRef<
  HTMLDivElement,
  { title: string; subtitle?: string; children: ReactNode }
>(function ShareCardFrame({ title, subtitle, children }, ref) {
  const legend = legendFooter();
  return (
    <div
      ref={ref}
      // Inline the load-bearing box metrics so the off-screen node is exact
      // regardless of ambient layout.
      style={{ width: CARD_WIDTH, height: CARD_HEIGHT }}
      className="flex flex-col justify-between overflow-hidden bg-canvas p-[72px] text-text-primary"
    >
      {/* Header — wordmark + subtitle */}
      <header className="flex items-start justify-between">
        <div className="flex flex-col gap-[8px]">
          <span className="display-caps text-[22px] text-text-secondary tracking-[0.3em]">
            crate
          </span>
          <span className="micro-caps text-[15px] text-text-muted">
            {title}
          </span>
        </div>
        {subtitle && (
          <span className="data-readout text-[15px] text-text-muted">
            {subtitle}
          </span>
        )}
      </header>

      {/* Body */}
      <div className="flex min-h-0 flex-1 flex-col justify-center py-[48px]">
        {children}
      </div>

      {/* OKLCH legend footer — the card's own colour key */}
      <footer className="flex items-end justify-between border-border-subtle border-t pt-[28px]">
        <div className="flex gap-[40px]">
          {legend.map((item) => (
            <div key={item.label} className="flex flex-col gap-[4px]">
              <span className="micro-caps text-[13px] text-text-muted">
                {item.label}
              </span>
              <span className="text-[15px] text-text-secondary">
                {item.detail}
              </span>
            </div>
          ))}
        </div>
        <span className="data-readout text-[13px] text-text-muted">
          colour = sound
        </span>
      </footer>
    </div>
  );
});
