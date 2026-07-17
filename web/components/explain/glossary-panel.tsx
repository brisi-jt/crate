"use client";

import { useMemo, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { allGlossaryEntries } from "@/lib/explain/glossary";
import { useUiStore } from "@/lib/store/ui";

/**
 * The glossary index — a browsable, searchable list of every explained term
 * in the app. Reachable from ⌘K. Positioned overlay on --surface-3 (same
 * floating-layer treatment as the palette, deliberately not a modal so the
 * map stays live underneath). Escape pops it (handled by the page pop-layer).
 */
export function GlossaryPanel() {
  const open = useUiStore((s) => s.glossaryOpen);
  const close = useUiStore((s) => s.closeGlossary);
  const [query, setQuery] = useState("");

  const entries = useMemo(() => allGlossaryEntries(), []);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      ({ entry }) =>
        entry.term.toLowerCase().includes(q) ||
        entry.what.toLowerCase().includes(q) ||
        entry.source.toLowerCase().includes(q),
    );
  }, [entries, query]);

  if (!open) return null;

  return (
    <div className="-translate-x-1/2 absolute top-[64px] left-1/2 z-40 flex w-[560px] flex-col rounded-md border border-border-subtle bg-surface-3">
      <header className="flex items-center justify-between border-border-subtle border-b px-md py-sm">
        <span className="display-caps text-micro text-text-secondary">
          Glossary
        </span>
        <button
          type="button"
          onClick={close}
          aria-label="Close glossary"
          className="micro-caps cursor-pointer text-text-muted hover:text-text-secondary"
        >
          ESC
        </button>
      </header>
      <input
        // biome-ignore lint/a11y/noAutofocus: the overlay opens focused so the user can type immediately, matching the ⌘K palette.
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search terms, meanings, or sources…"
        aria-label="Search the glossary"
        className="border-border-subtle border-b bg-transparent px-md py-sm text-sm text-text-primary outline-none placeholder:text-text-muted"
      />
      <ScrollArea className="max-h-[420px]">
        <div className="flex flex-col">
          {filtered.length === 0 ? (
            <p className="px-md py-lg text-center text-sm text-text-muted">
              Nothing matches.
            </p>
          ) : (
            filtered.map(({ ref, entry }) => (
              <div
                key={ref}
                className="flex flex-col gap-2xs border-border-subtle border-b px-md py-sm last:border-b-0"
              >
                <div className="flex items-baseline justify-between gap-sm">
                  <span className="font-bold text-sm text-text-primary">
                    {entry.term}
                  </span>
                  {entry.unit && (
                    <span className="data-readout text-micro text-text-muted">
                      {entry.unit}
                    </span>
                  )}
                </div>
                <p className="text-[12px] leading-snug text-text-secondary">
                  {entry.what}
                </p>
                <p className="text-[12px] leading-snug text-text-secondary">
                  <span className="micro-caps text-text-muted">How </span>
                  {entry.how}
                </p>
                <p className="text-[11px] leading-snug text-text-muted">
                  <span className="micro-caps">Source </span>
                  {entry.source}
                </p>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
