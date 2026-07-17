"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import {
  BarRow,
  ExtendedEmpty,
} from "@/components/insights/extended/extended-kit";
import type { JournalSection, RadioSection } from "@/lib/api/schemas-extended";
import { formatRate } from "@/lib/insights/extended-view";

/**
 * RADIO — how much of what a generated session serves you actually keep, and
 * how often the unfamiliar tracks land.
 */
export function RadioInsightsSection({ radio }: { radio: RadioSection }) {
  const { keep_rate, discovery_conversion } = radio;
  if (keep_rate.total === 0) {
    return (
      <ExtendedEmpty note="No radio sessions judged yet. Generate radio and keep or skip its tracks — your keep rate and discovery conversion appear here." />
    );
  }
  const maxSeed = Math.max(
    0.01,
    ...keep_rate.by_seed.map((s) => s.keep_rate ?? 0),
  );
  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap gap-lg">
        <ExplainReadout
          metric="radio_keep_rate"
          label="Keep rate"
          value={formatRate(keep_rate.keep_rate)}
        />
        <ExplainReadout
          metric="discovery_conversion"
          label="Discovery kept"
          value={formatRate(discovery_conversion.conversion_rate)}
        />
      </div>
      {keep_rate.by_seed.length > 0 && (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">Keep rate by seed</span>
          <div className="flex flex-col gap-2xs">
            {keep_rate.by_seed.map((s) => (
              <BarRow
                key={s.seed_kind}
                label={s.seed_kind}
                fraction={(s.keep_rate ?? 0) / maxSeed}
                value={formatRate(s.keep_rate)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * CURATION — how busily you edit, the mix of edits, how often you undo, and
 * which whole-set operations you reach for.
 */
export function JournalInsightsSection({
  journal,
}: {
  journal: JournalSection;
}) {
  const { curation_intensity, bulk_algebra } = journal;
  if (curation_intensity.total === 0) {
    return (
      <ExtendedEmpty note="No edits recorded yet. As you file, move, and bulk-edit tracks, your curation pace and operation mix build up here." />
    );
  }
  const maxOp = Math.max(1, ...curation_intensity.op_mix.map((o) => o.count));
  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap gap-lg">
        <ExplainReadout
          metric="curation_intensity"
          label="Edits / week"
          value={curation_intensity.edits_per_week.toFixed(1)}
        />
        <ExplainReadout
          metric="curation_intensity"
          label="Undo rate"
          value={formatRate(curation_intensity.undo_rate)}
        />
      </div>
      {curation_intensity.op_mix.length > 0 && (
        <div className="flex flex-col gap-xs">
          <span className="micro-caps text-text-muted">Edit mix</span>
          <div className="flex flex-col gap-2xs">
            {curation_intensity.op_mix.map((o) => (
              <BarRow
                key={o.op_type}
                label={o.op_type.replace(/_/g, " ")}
                fraction={o.count / maxOp}
                value={o.count.toLocaleString()}
              />
            ))}
          </div>
        </div>
      )}
      {bulk_algebra.operations.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="bulk_algebra">
            <span className="micro-caps text-text-muted">Bulk operations</span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {bulk_algebra.operations.map((o) => (
              <div key={o.operation} className="flex items-baseline gap-sm">
                <span className="flex-1 text-sm text-text-primary capitalize">
                  {o.operation}
                </span>
                <span className="data-readout text-micro text-text-muted">
                  {o.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
