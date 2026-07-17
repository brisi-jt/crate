"use client";

import { useState } from "react";
import { DnaSection } from "@/components/dashboard/dna-section";
import { ListeningRhythmSection } from "@/components/dashboard/listening-rhythm-section";
import { ObscuritySection } from "@/components/dashboard/obscurity-section";
import { TasteDriftSection } from "@/components/dashboard/taste-drift-section";
import { SurveySection } from "@/components/insights/survey-section";
import {
  useListeningDashboard,
  useObscurity,
  useTasteDrift,
} from "@/hooks/api/use-competitive";
import { useExtendedInsights } from "@/hooks/api/use-extended-insights";
import type { ListeningRange } from "@/lib/api/schemas-competitive";
import { hasImportedHistory } from "@/lib/competitive/dashboard-view";

function SectionError({
  label,
  onRetry,
}: {
  label: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-xs">
      <span className="micro-caps text-danger">{label} UNAVAILABLE</span>
      <button
        type="button"
        onClick={onRetry}
        className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
      >
        Retry
      </button>
    </div>
  );
}

function SectionSkeleton() {
  return <div className="h-[120px] animate-pulse rounded-md bg-surface-2" />;
}

/**
 * The DASHBOARD dock (640px) — the competitor-parity identity surface: the
 * "crate DNA" share card (S1), the listening-rhythm dashboard (F1), obscurity
 * (F3), and taste drift (F5). Each section carries its own explains.
 */
export function DashboardPanelContent() {
  const [range, setRange] = useState<ListeningRange>("all_time");
  const [snapshotId, setSnapshotId] = useState<number | null>(null);

  const dashboard = useListeningDashboard(range);
  const obscurity = useObscurity();
  const drift = useTasteDrift(snapshotId);
  // The all_time / since_crate toggle only makes sense once imported history
  // extends the play record past crate's own captures. The extended-insights
  // coverage is the authoritative import signal (play_events > since_crate).
  const extended = useExtendedInsights();
  const showRangeToggle = extended.data
    ? hasImportedHistory({
        totalPlays: extended.data.coverage.play_events,
        sinceCratePlays: extended.data.coverage.since_crate_plays,
      })
    : false;

  return (
    <div className="flex flex-col gap-lg">
      <SurveySection title="CRATE DNA">
        <DnaSection />
      </SurveySection>

      <SurveySection title="LISTENING RHYTHM">
        {dashboard.isPending && <SectionSkeleton />}
        {dashboard.isError && (
          <SectionError
            label="LISTENING RHYTHM"
            onRetry={() => dashboard.refetch()}
          />
        )}
        {dashboard.data && (
          <ListeningRhythmSection
            data={dashboard.data}
            range={range}
            onRangeChange={setRange}
            showRangeToggle={showRangeToggle}
          />
        )}
      </SurveySection>

      <SurveySection title="OBSCURITY" defaultOpen={false}>
        {obscurity.isPending && <SectionSkeleton />}
        {obscurity.isError && (
          <SectionError label="OBSCURITY" onRetry={() => obscurity.refetch()} />
        )}
        {obscurity.data && <ObscuritySection data={obscurity.data} />}
      </SurveySection>

      <SurveySection title="TASTE DRIFT" defaultOpen={false}>
        {drift.isPending && <SectionSkeleton />}
        {drift.isError && (
          <SectionError label="TASTE DRIFT" onRetry={() => drift.refetch()} />
        )}
        {drift.data && (
          <TasteDriftSection
            data={drift.data}
            selectedSnapshotId={snapshotId}
            onSelect={setSnapshotId}
          />
        )}
      </SurveySection>
    </div>
  );
}
