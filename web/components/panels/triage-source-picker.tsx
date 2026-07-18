"use client";

import { useEffect, useRef, useState } from "react";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

/**
 * Searchable owned-playlist picker for setting the triage source. Unlike the
 * bulk-ops TargetPicker (a plain list), this filters as you type — JT owns
 * hundreds of playlists, so search is the point. Every owned playlist is
 * pickable as a source, including ones held out of triage (those are badged).
 */
export function TriageSourcePicker({
  options,
  value,
  onPick,
}: {
  options: Array<{ id: number; name: string; excluded?: boolean }>;
  value: number | null;
  onPick: (id: number) => void;
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
        {current ? current.name || "Untitled" : "PICK A PLAYLIST…"} ▾
      </button>
      {open && (
        <div className="absolute top-full left-0 z-30 mt-2xs w-[260px] rounded-md border border-border-subtle bg-surface-3">
          <Command className="bg-surface-3">
            <CommandInput
              autoFocus
              placeholder="Search owned playlists…"
              className="text-text-primary placeholder:text-text-muted"
            />
            <CommandList className="max-h-[240px]">
              <CommandEmpty className="py-md text-center text-sm text-text-muted">
                No match.
              </CommandEmpty>
              <CommandGroup>
                {options.map((option) => (
                  <CommandItem
                    key={option.id}
                    value={`${option.name} ${option.id}`}
                    onSelect={() => {
                      onPick(option.id);
                      setOpen(false);
                    }}
                    className="data-[selected=true]:bg-surface-2"
                  >
                    <span className="truncate text-text-secondary">
                      {option.name || "Untitled"}
                    </span>
                    {option.excluded && (
                      <span className="ml-auto shrink-0 text-micro text-text-muted">
                        excluded
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </div>
      )}
    </div>
  );
}

export { TriageSourcePicker as SourcePicker };
