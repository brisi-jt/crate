"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Small single-value picker for docked-panel actions (seed/target playlist,
 * frontier genre). The bulk-ops picker pattern: readout-styled trigger, a
 * surface-3 list floated above it, outside-click dismiss.
 */
export function TargetPicker({
  options,
  value,
  onPick,
  placeholder = "TARGET PLAYLIST",
  emptyNote = "No owned playlists yet.",
}: {
  options: Array<{ id: number; name: string }>;
  value: number | null;
  onPick: (id: number) => void;
  placeholder?: string;
  emptyNote?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = options.find((o) => o.id === value) ?? null;

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="data-readout cursor-pointer rounded-sm border border-border-subtle bg-surface-2 px-sm py-2xs text-micro text-text-secondary hover:text-text-primary"
      >
        {current ? current.name : placeholder} ▾
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-2xs max-h-[240px] w-[220px] overflow-y-auto rounded-md border border-border-subtle bg-surface-3 py-2xs">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => {
                onPick(option.id);
                setOpen(false);
              }}
              className="block w-full cursor-pointer truncate px-sm py-2xs text-left text-sm text-text-secondary hover:bg-surface-2 hover:text-text-primary"
            >
              {option.name}
            </button>
          ))}
          {options.length === 0 && (
            <span className="block px-sm py-2xs text-sm text-text-muted">
              {emptyNote}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
