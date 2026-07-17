"use client";

import { CrossTableInsightsSection } from "@/components/insights/extended/cross-table-section";
import { ExtendedPinStrip } from "@/components/insights/extended/extended-pin-strip";
import { FeedbackInsightsSection } from "@/components/insights/extended/feedback-section";
import { PlayHistorySection } from "@/components/insights/extended/play-history-section";
import {
  JournalInsightsSection,
  RadioInsightsSection,
} from "@/components/insights/extended/radio-journal-section";
import { SavedInsightsSection } from "@/components/insights/extended/saved-section";
import { TopItemsInsightsSection } from "@/components/insights/extended/top-items-section";
import { SurveySection } from "@/components/insights/survey-section";
import { useExtendedInsights } from "@/hooks/api/use-extended-insights";
import { hasPlayHistory } from "@/lib/insights/extended-view";

/**
 * The EXTENDED SURVEY — 24 grounded readings mined from the seven deep tables
 * that the base survey never touches. Rendered as a stack of collapsible survey
 * sections beneath the base survey, each carrying its own explains and a quiet
 * pending state where its source table is still empty.
 */
export function ExtendedInsights() {
  const extended = useExtendedInsights();

  if (extended.isPending) {
    return (
      <div className="flex flex-col gap-md">
        {["LISTENING", "SAVED SONGS", "FEEDBACK", "CURATION"].map((label) => (
          <div key={label} className="flex flex-col gap-xs">
            <span className="micro-caps text-text-muted">{label}</span>
            <div className="h-[64px] animate-pulse rounded-md bg-surface-2" />
          </div>
        ))}
      </div>
    );
  }

  if (extended.isError || !extended.data) {
    return (
      <div className="flex flex-col items-start gap-xs">
        <span className="micro-caps text-danger">
          EXTENDED SURVEY UNAVAILABLE
        </span>
        <button
          type="button"
          onClick={() => extended.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  const data = extended.data;
  const { coverage } = data;
  const importedPlays = coverage.play_events - coverage.since_crate_plays;

  return (
    <div className="flex flex-col gap-lg">
      <ExtendedPinStrip />

      <SurveySection
        title="LISTENING"
        meta={`${coverage.play_events.toLocaleString()} PLAYS`}
      >
        <div className="flex flex-col gap-md">
          {hasPlayHistory(coverage) && (
            <p className="text-sm text-text-muted">
              {importedPlays.toLocaleString()} of these are imported history
              from before crate — this reading spans your all-time listening.
            </p>
          )}
          <PlayHistorySection
            play={data.play_events}
            totalPlays={coverage.play_events}
          />
        </div>
      </SurveySection>

      <SurveySection
        title="SAVED SONGS"
        meta={`${coverage.total_saved.toLocaleString()} SAVED`}
        defaultOpen={false}
      >
        <SavedInsightsSection saved={data.saved} />
      </SurveySection>

      <SurveySection title="SUGGESTION FEEDBACK" defaultOpen={false}>
        <FeedbackInsightsSection feedback={data.feedback} />
      </SurveySection>

      <SurveySection
        title="TOP ITEMS"
        meta={`${coverage.top_snapshots} READINGS`}
        defaultOpen={false}
      >
        <TopItemsInsightsSection topItems={data.top_items} />
      </SurveySection>

      <SurveySection title="RADIO" defaultOpen={false}>
        <RadioInsightsSection radio={data.radio} />
      </SurveySection>

      <SurveySection title="CURATION" defaultOpen={false}>
        <JournalInsightsSection journal={data.journal} />
      </SurveySection>

      <SurveySection title="CROSS-CUTTING" defaultOpen={false}>
        <CrossTableInsightsSection cross={data.cross_table} />
      </SurveySection>
    </div>
  );
}
