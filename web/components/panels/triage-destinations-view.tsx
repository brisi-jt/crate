"use client";

import { Search } from "lucide-react";
import { useMemo, useReducer, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useSetTriageDestinations,
  useTriageDestinations,
} from "@/hooks/api/use-triage";
import { ApiError } from "@/lib/api/errors";
import {
  type Destination,
  destinationsBody,
  eligibleCount,
  initDestinations,
  isDirty,
  reduceDestinations,
  visibleIds,
} from "@/lib/triage/destinations";

/**
 * Scope which owned playlists are filing destinations. Spotify's API can't see
 * playlist folders, so eligible/excluded is tracked here in crate. Checked =
 * eligible; unchecked = held out of triage (dropped from suggestions and the
 * orphan filter). Search + select all / none / invert act on the filtered set.
 */
export function TriageDestinationsView({ onDone }: { onDone: () => void }) {
  const destinations = useTriageDestinations();

  if (destinations.isPending) {
    return <DestinationsSkeleton />;
  }
  if (destinations.isError || !destinations.data) {
    return (
      <div className="flex flex-col items-start gap-xs rounded-md border border-danger/40 bg-surface-1 px-md py-sm">
        <span className="micro-caps text-danger">
          Couldn't load destinations
        </span>
        <button
          type="button"
          onClick={() => destinations.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  const items: Destination[] = destinations.data.items.map((d) => ({
    id: d.id,
    name: d.name,
    excluded: d.triage_excluded,
  }));
  return <DestinationsEditor items={items} onDone={onDone} />;
}

function DestinationsEditor({
  items,
  onDone,
}: {
  items: Destination[];
  onDone: () => void;
}) {
  const [state, dispatch] = useReducer(
    reduceDestinations,
    items,
    initDestinations,
  );
  const [saved, setSaved] = useState(false);
  const save = useSetTriageDestinations();

  const visible = visibleIds(state);
  const visibleItems = useMemo(
    () => visible.map((id) => ({ id, name: state.names[id] ?? "" })),
    [visible, state.names],
  );
  const eligible = eligibleCount(state);
  const dirty = isDirty(state);

  const onSave = () => {
    save.mutate(destinationsBody(state).excluded_playlist_ids, {
      onSuccess: () => {
        setSaved(true);
        toast("Filing destinations updated.");
        onDone();
      },
      onError: (error) => {
        const code =
          error instanceof ApiError ? error.problem?.error_code : undefined;
        toast.error(
          code === "INVALID_TRIAGE_PLAYLIST"
            ? "One of those isn't a live owned playlist anymore — reopen and retry."
            : "Couldn't save destinations.",
        );
      },
    });
  };

  return (
    <section className="flex flex-col gap-md">
      <div className="flex flex-col gap-2xs">
        <span className="micro-caps text-text-muted">Filing destinations</span>
        <span className="max-w-[52ch] text-micro text-text-secondary">
          Uncheck a playlist to hold it out of triage — Spotify's API can't see
          your folders, so this is where you scope where songs get filed.
        </span>
      </div>

      <label className="flex items-center gap-sm rounded-md border border-border-subtle bg-surface-2 px-sm py-2xs">
        <Search className="size-[14px] text-text-muted" />
        <input
          value={state.search}
          onChange={(e) => dispatch({ type: "SEARCH", query: e.target.value })}
          placeholder="Search owned playlists…"
          className="w-full bg-transparent text-sm text-text-primary outline-none placeholder:text-text-muted"
          aria-label="Search owned playlists"
        />
      </label>

      <div className="flex items-center justify-between">
        <span className="data-readout text-micro text-text-secondary">
          {eligible} of {state.order.length} eligible
        </span>
        <div className="flex items-center gap-sm">
          <BulkButton onClick={() => dispatch({ type: "SELECT_ALL" })}>
            All
          </BulkButton>
          <BulkButton onClick={() => dispatch({ type: "SELECT_NONE" })}>
            None
          </BulkButton>
          <BulkButton onClick={() => dispatch({ type: "INVERT" })}>
            Invert
          </BulkButton>
        </div>
      </div>

      <div className="flex max-h-[340px] flex-col gap-2xs overflow-y-auto pr-2xs">
        {visibleItems.length === 0 ? (
          <span className="py-md text-center text-sm text-text-muted">
            No match.
          </span>
        ) : (
          visibleItems.map((item) => {
            const isEligible = state.eligible[item.id];
            return (
              <div
                key={item.id}
                className="flex items-center gap-sm rounded-sm px-2xs py-2xs hover:bg-surface-2"
              >
                <Checkbox
                  id={`dest-${item.id}`}
                  checked={isEligible}
                  onCheckedChange={() =>
                    dispatch({ type: "TOGGLE", id: item.id })
                  }
                  aria-label={`${item.name || "Untitled"} eligible for triage`}
                />
                <label
                  htmlFor={`dest-${item.id}`}
                  className={`flex-1 cursor-pointer truncate text-sm ${
                    isEligible ? "text-text-primary" : "text-text-muted"
                  }`}
                >
                  {item.name || "Untitled"}
                </label>
                {!isEligible && (
                  <Badge
                    variant="outline"
                    className="shrink-0 rounded-sm text-micro text-text-muted"
                  >
                    EXCLUDED
                  </Badge>
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="flex items-center gap-sm">
        <button
          type="button"
          disabled={!dirty || save.isPending}
          onClick={onSave}
          className="display-caps cursor-pointer rounded-sm bg-amber px-md py-xs text-amber-ink text-micro transition-colors hover:bg-amber-press disabled:cursor-default disabled:opacity-40"
        >
          {save.isPending ? "Saving…" : "Save destinations"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
        >
          {dirty && !saved ? "Cancel" : "Done"}
        </button>
      </div>
    </section>
  );
}

function BulkButton({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="micro-caps cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-text-secondary hover:text-text-primary"
    >
      {children}
    </button>
  );
}

function DestinationsSkeleton() {
  return (
    <div className="flex flex-col gap-md">
      <Skeleton className="h-[20px] w-1/2" />
      <Skeleton className="h-[34px] w-full" />
      {[0, 1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-[24px] w-full" />
      ))}
    </div>
  );
}
