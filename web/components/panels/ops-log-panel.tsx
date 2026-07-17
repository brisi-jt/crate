"use client";

import { toast } from "sonner";
import { Explain } from "@/components/explain/explain";
import { Skeleton } from "@/components/ui/skeleton";
import { useJournal, useUndoJournal } from "@/hooks/api/use-journal";
import type { JournalEntry } from "@/lib/api/schemas";

function formatTimestamp(iso: string): string {
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatRevertTime(iso: string): string {
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "applied"
      ? "text-success border-success/40"
      : status === "partial"
        ? "text-danger border-danger/40"
        : status === "undone"
          ? "text-text-muted border-border-subtle"
          : "text-text-secondary border-border-subtle";
  return (
    <span className={`data-readout rounded-xs border px-xs text-micro ${tone}`}>
      {status}
    </span>
  );
}

function OpsLogRow({ entry }: { entry: JournalEntry }) {
  const undo = useUndoJournal();
  const undoable = entry.status === "applied" || entry.status === "partial";
  const reverted = entry.status === "undone";

  return (
    <div className="flex items-center gap-sm border-border-subtle border-b py-sm">
      <span className="data-readout shrink-0 text-micro text-text-muted">
        {formatTimestamp(entry.created_at)}
      </span>
      <span
        className={`min-w-0 flex-1 truncate text-sm ${reverted ? "text-text-muted line-through" : "text-text-secondary"}`}
        title={entry.summary}
      >
        {entry.summary}
      </span>
      <StatusBadge status={entry.status} />
      {undoable && (
        <button
          type="button"
          disabled={undo.isPending}
          className="micro-caps shrink-0 cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-text-muted hover:border-border-strong hover:text-text-primary"
          onClick={() =>
            undo.mutate(entry.id, {
              onError: (error) => {
                toast.error(
                  error instanceof Error ? error.message : "Revert failed",
                );
              },
            })
          }
        >
          Revert
        </button>
      )}
      {reverted && entry.undone_at && (
        <span className="data-readout shrink-0 text-micro text-success">
          REVERTED {formatRevertTime(entry.undone_at)}
        </span>
      )}
    </div>
  );
}

/**
 * The operations log: every mutation crate has performed, newest first,
 * one-click revertible (journal-backed). History is never deleted — undone
 * entries strike through and stay.
 */
export function OpsLogPanelContent() {
  const journal = useJournal();

  if (journal.isPending) {
    return (
      <div className="flex flex-col gap-xs">
        {Array.from({ length: 6 }, (_, i) => `oplog-skeleton-${i}`).map(
          (key) => (
            <Skeleton key={key} className="h-9 w-full bg-surface-2" />
          ),
        )}
      </div>
    );
  }

  if (journal.isError) {
    return (
      <p className="text-sm text-text-secondary">
        Couldn't load the operations log —{" "}
        <button
          type="button"
          className="cursor-pointer underline"
          onClick={() => journal.refetch()}
        >
          retry
        </button>
        .
      </p>
    );
  }

  const items = journal.data?.items ?? [];
  if (items.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        No mutations recorded yet — every write lands here, permanently and
        revertibly.
      </p>
    );
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-md pb-sm">
        <Explain metric="op_status">
          <span className="micro-caps text-text-muted">Status</span>
        </Explain>
        <Explain metric="dedupe">
          <span className="micro-caps text-text-muted">De-duplicate</span>
        </Explain>
      </div>
      {items.map((entry) => (
        <OpsLogRow key={entry.id} entry={entry} />
      ))}
    </div>
  );
}
