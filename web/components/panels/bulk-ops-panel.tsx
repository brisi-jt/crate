"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Readout } from "@/components/panels/right-dock";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useUndoJournal } from "@/hooks/api/use-journal";
import { useOpsApply, useOpsPreview } from "@/hooks/api/use-ops";
import { usePlaylists } from "@/hooks/api/use-playlists";
import { ApiError } from "@/lib/api/errors";
import type { ApplyResult, OpPreview } from "@/lib/api/schemas";
import {
  type ArmState,
  armReducer,
  IDLE,
  isArmed,
  secondsRemaining,
} from "@/lib/ops/arm";
import {
  commitIsDestructive,
  commitLabel,
  manifestIsEmpty,
  manifestRows,
} from "@/lib/ops/manifest";

const OPERATIONS = [
  { value: "union", label: "Union", symbol: "∪" },
  { value: "difference", label: "Difference", symbol: "−" },
  { value: "intersect", label: "Intersect", symbol: "∩" },
  { value: "dedupe", label: "Dedupe", symbol: "≡" },
  { value: "sync_subset_to_parent", label: "Subset → parent", symbol: "⊂" },
] as const;

type Operation = (typeof OPERATIONS)[number]["value"];

/** Which operand slots an operation uses. */
function shape(op: Operation) {
  return {
    multiSource: op === "union" || op === "difference" || op === "intersect",
    hasTarget: op !== "dedupe",
    allowNewTarget: op === "union" || op === "difference" || op === "intersect",
  };
}

interface PickerOption {
  id: number;
  name: string;
}

function PlaylistPicker({
  options,
  value,
  placeholder,
  onPick,
}: {
  options: PickerOption[];
  value: number | null;
  placeholder: string;
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
        {current ? current.name : placeholder} ▾
      </button>
      {open && (
        <div className="absolute top-full left-0 z-30 mt-2xs max-h-[240px] w-[220px] overflow-y-auto rounded-md border border-border-subtle bg-surface-3 py-2xs">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              className="block w-full cursor-pointer truncate px-sm py-2xs text-left text-sm text-text-secondary hover:bg-surface-2 hover:text-text-primary"
              onClick={() => {
                onPick(option.id);
                setOpen(false);
              }}
            >
              {option.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Bulk playlist algebra (design brief D7, tier 2): build a set expression,
 * preview the exact delta manifest, then commit through the ARM → COMMIT
 * switchgear. The manifest IS the confirmation — no modal ever appears.
 * ARM decays after 10 idle seconds; any expression change disarms.
 */
export function BulkOpsPanelContent({
  initialSourceId,
}: {
  initialSourceId?: number;
}) {
  const playlists = usePlaylists();
  const previewMutation = useOpsPreview();
  const applyMutation = useOpsApply();
  const undo = useUndoJournal();

  const [operation, setOperation] = useState<Operation>("dedupe");
  const [sourceIds, setSourceIds] = useState<number[]>(
    initialSourceId !== undefined ? [initialSourceId] : [],
  );
  const [targetId, setTargetId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [preview, setPreview] = useState<OpPreview | null>(null);
  const [arm, setArm] = useState<ArmState>(IDLE);
  const [applied, setApplied] = useState<ApplyResult | null>(null);
  const [stale, setStale] = useState(false);

  // Visible decay countdown: tick 4×/s while armed.
  useEffect(() => {
    if (!isArmed(arm)) return;
    const interval = setInterval(() => {
      setArm((state) => armReducer(state, { type: "tick", now: Date.now() }));
    }, 250);
    return () => clearInterval(interval);
  }, [arm]);

  const options: PickerOption[] =
    playlists.data?.items
      .filter((p) => !p.is_deleted)
      .map((p) => ({ id: p.id, name: p.name })) ?? [];
  const ops = shape(operation);

  function disarmAndInvalidate() {
    setArm(IDLE);
    setPreview(null);
    setApplied(null);
    setStale(false);
  }

  function runPreview() {
    setStale(false);
    setApplied(null);
    setArm(IDLE);
    previewMutation.mutate(
      {
        operation,
        sourceIds,
        targetId: ops.hasTarget ? targetId : null,
        newPlaylistName:
          ops.allowNewTarget && targetId === null && newName.trim()
            ? newName.trim()
            : null,
      },
      {
        onSuccess: setPreview,
        onError: (error) => {
          toast.error(
            error instanceof Error ? error.message : "Preview failed",
          );
        },
      },
    );
  }

  function commit() {
    if (!preview || !isArmed(arm)) return;
    setArm((state) => armReducer(state, { type: "commit" }));
    applyMutation.mutate(preview.preview_id, {
      onSuccess: (result) => {
        setApplied(result);
        setPreview(null);
        if (result.status === "applied") {
          toast(
            `Applied · ${commitLabel(preview.manifest).replace("COMMIT ", "")}`,
            {
              duration: 8000,
              action: {
                label: "UNDO",
                onClick: () => undo.mutate(result.journal_id),
              },
            },
          );
        }
      },
      onError: (error) => {
        if (
          error instanceof ApiError &&
          error.problem?.error_code === "PREVIEW_STALE"
        ) {
          setStale(true);
          setPreview(null);
          return;
        }
        toast.error(error instanceof Error ? error.message : "Apply failed");
      },
    });
  }

  const manifest = preview?.manifest ?? null;
  const rows = manifest ? manifestRows(manifest) : [];
  const destructive = manifest ? commitIsDestructive(manifest) : false;
  const remaining = secondsRemaining(arm, Date.now());
  const canPreview =
    sourceIds.length > 0 &&
    (!ops.hasTarget ||
      targetId !== null ||
      (ops.allowNewTarget && newName.trim() !== ""));

  return (
    <>
      {/* Expression builder */}
      <div className="flex flex-col gap-sm">
        <span className="micro-caps text-text-muted">Operation</span>
        <div className="flex flex-wrap gap-xs">
          {OPERATIONS.map((op) => (
            <button
              key={op.value}
              type="button"
              data-active={operation === op.value || undefined}
              className="micro-caps cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-text-muted hover:text-text-primary data-[active]:border-amber data-[active]:text-amber"
              onClick={() => {
                setOperation(op.value);
                disarmAndInvalidate();
              }}
            >
              {op.symbol} {op.label}
            </button>
          ))}
        </div>

        <span className="micro-caps text-text-muted">
          {ops.multiSource
            ? "Sources"
            : operation === "dedupe"
              ? "Playlist"
              : "Subset"}
        </span>
        <div className="flex flex-wrap items-center gap-xs">
          {sourceIds.map((id, index) => (
            <button
              key={id}
              type="button"
              title="Remove operand"
              className="data-readout cursor-pointer rounded-sm border border-border-subtle px-sm py-2xs text-micro text-text-primary hover:border-danger hover:text-danger"
              onClick={() => {
                setSourceIds(sourceIds.filter((s) => s !== id));
                disarmAndInvalidate();
              }}
            >
              {options.find((o) => o.id === id)?.name ?? id}
              {index === 0 && operation === "difference" && sourceIds.length > 1
                ? " (base)"
                : ""}{" "}
              ✕
            </button>
          ))}
          {(ops.multiSource ? true : sourceIds.length === 0) && (
            <PlaylistPicker
              options={options.filter((o) => !sourceIds.includes(o.id))}
              value={null}
              placeholder={
                sourceIds.length > 0 ? "Add source" : "Pick playlist"
              }
              onPick={(id) => {
                setSourceIds([...sourceIds, id]);
                disarmAndInvalidate();
              }}
            />
          )}
        </div>

        {ops.hasTarget && (
          <>
            <span className="micro-caps text-text-muted">
              {operation === "sync_subset_to_parent" ? "Parent" : "Target"}
            </span>
            <div className="flex flex-wrap items-center gap-xs">
              <PlaylistPicker
                options={options.filter((o) => !sourceIds.includes(o.id))}
                value={targetId}
                placeholder="Existing playlist"
                onPick={(id) => {
                  setTargetId(id);
                  setNewName("");
                  disarmAndInvalidate();
                }}
              />
              {ops.allowNewTarget && (
                <>
                  <span className="micro-caps text-text-muted">or new</span>
                  <input
                    value={newName}
                    placeholder="New playlist name"
                    className="rounded-sm border border-border-subtle bg-surface-2 px-sm py-2xs text-sm text-text-primary placeholder:text-text-muted"
                    onChange={(event) => {
                      setNewName(event.target.value);
                      setTargetId(null);
                      disarmAndInvalidate();
                    }}
                  />
                </>
              )}
              {targetId !== null && (
                <button
                  type="button"
                  className="micro-caps cursor-pointer text-text-muted hover:text-text-primary"
                  onClick={() => {
                    setTargetId(null);
                    disarmAndInvalidate();
                  }}
                >
                  Clear
                </button>
              )}
            </div>
          </>
        )}

        <div>
          <Button
            variant="ghost"
            size="sm"
            disabled={!canPreview || previewMutation.isPending}
            onClick={runPreview}
            className="micro-caps border border-border-subtle"
          >
            {previewMutation.isPending ? "Computing…" : "Preview delta"}
          </Button>
        </div>
      </div>

      {stale && (
        <p className="border border-danger/40 rounded-md px-md py-sm text-sm text-danger">
          The library changed since this preview — the delta no longer holds.{" "}
          <button
            type="button"
            className="cursor-pointer underline"
            onClick={runPreview}
          >
            Re-preview
          </button>
          .
        </p>
      )}

      {/* Delta manifest — the confirmation surface */}
      {manifest && (
        <div className="flex min-h-0 flex-1 flex-col gap-sm">
          {manifestIsEmpty(manifest) ? (
            <p className="text-sm text-text-secondary">
              Nothing to change — the expression result already holds.
            </p>
          ) : (
            <>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border-strong hover:bg-transparent">
                      <TableHead className="micro-caps h-8 w-6 text-text-muted" />
                      <TableHead className="micro-caps h-8 text-text-muted">
                        Track
                      </TableHead>
                      <TableHead className="micro-caps h-8 text-text-muted">
                        Playlist
                      </TableHead>
                      <TableHead className="micro-caps h-8 text-right text-text-muted">
                        Δ
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow
                        key={row.key}
                        className="border-border-subtle text-sm hover:bg-surface-2"
                      >
                        <TableCell
                          className={`data-readout py-xs ${row.delta === "add" ? "text-success" : "text-danger"}`}
                        >
                          {row.delta === "add" ? "+" : "−"}
                        </TableCell>
                        <TableCell className="py-xs">
                          <span className="text-text-primary">{row.title}</span>
                          {row.artist && (
                            <span className="text-text-secondary">
                              {" "}
                              · {row.artist}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="py-xs text-text-secondary">
                          {row.playlist}
                        </TableCell>
                        <TableCell className="data-readout py-xs text-right text-micro text-text-muted">
                          {row.delta === "add" ? "add" : `pos ${row.position}`}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="flex gap-xl">
                <Readout label="Adds" value={`+${manifest.summary.adds}`} />
                <Readout
                  label="Removes"
                  value={`−${manifest.summary.removes}`}
                />
                <Readout
                  label="Playlists"
                  value={String(manifest.summary.playlists)}
                />
              </div>

              {/* ARM → COMMIT switchgear */}
              <div className="flex items-center gap-md border-border-subtle border-t pt-md">
                <button
                  type="button"
                  data-armed={isArmed(arm) || undefined}
                  className="display-caps cursor-pointer rounded-sm border border-border-strong px-lg py-xs text-micro text-text-secondary hover:text-text-primary data-[armed]:border-amber data-[armed]:bg-amber data-[armed]:text-amber-ink"
                  onClick={() =>
                    setArm((state) =>
                      isArmed(state)
                        ? armReducer(state, { type: "disarm" })
                        : armReducer(state, { type: "arm", now: Date.now() }),
                    )
                  }
                >
                  {isArmed(arm) ? "ARMED" : "ARM"}
                </button>
                {remaining !== null && (
                  <span className="data-readout text-micro text-amber">
                    DISARMS IN {String(remaining).padStart(2, "0")}s
                  </span>
                )}
                <button
                  type="button"
                  disabled={!isArmed(arm) || applyMutation.isPending}
                  data-destructive={destructive || undefined}
                  className="display-caps ml-auto cursor-pointer rounded-sm border border-border-strong px-lg py-xs text-micro text-text-muted disabled:cursor-default enabled:border-amber enabled:bg-amber enabled:text-amber-ink enabled:data-[destructive]:border-danger enabled:data-[destructive]:bg-danger enabled:data-[destructive]:text-text-primary"
                  onClick={commit}
                >
                  {applyMutation.isPending
                    ? "COMMITTING…"
                    : commitLabel(manifest)}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Apply outcome, incl. partial-failure surfacing */}
      {applied && (
        <div className="flex flex-col gap-xs border border-border-subtle rounded-md px-md py-sm">
          <span
            className={`micro-caps ${applied.status === "applied" ? "text-success" : "text-danger"}`}
          >
            {applied.status === "applied" ? "Applied" : "Partially applied"}
          </span>
          {applied.results.map((result) => (
            <div
              key={`${result.name}-${result.playlist_id}`}
              className="flex items-center gap-sm text-sm"
            >
              <span className="text-text-primary">{result.name}</span>
              <span
                className={`data-readout ml-auto text-micro ${result.status === "applied" ? "text-success" : "text-danger"}`}
              >
                {result.status}
              </span>
            </div>
          ))}
          {applied.status !== "applied" && (
            <p className="text-sm text-text-secondary">
              The journal entry holds per-playlist results — revert it from the
              operations log to restore everything that did apply.
            </p>
          )}
        </div>
      )}
    </>
  );
}
