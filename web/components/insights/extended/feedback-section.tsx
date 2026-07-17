"use client";

import { Explain, ExplainReadout } from "@/components/explain/explain";
import {
  BarRow,
  DeltaStrip,
  ExtendedEmpty,
  NameLine,
} from "@/components/insights/extended/extended-kit";
import type { FeedbackSection } from "@/lib/api/schemas-extended";

/**
 * SUGGESTION FEEDBACK — the sound of your yes. Which sources you accept from,
 * how accepted candidates differ from rejected ones, which artists you keep
 * saying yes to, and where candidates sit in their journey.
 */
export function FeedbackInsightsSection({
  feedback,
}: {
  feedback: FeedbackSection;
}) {
  const {
    curation_totals,
    source_efficacy,
    taste_of_yes,
    per_artist_affinity,
  } = feedback;
  const reviewed =
    curation_totals.accept + curation_totals.reject + curation_totals.skip;

  if (reviewed === 0) {
    return (
      <ExtendedEmpty note="You haven't judged any suggestions yet. As you accept and reject candidates, the sound of your yes and your best sources surface here." />
    );
  }

  const maxRate = Math.max(0.01, ...source_efficacy.map((s) => s.accept_rate));

  return (
    <div className="flex flex-col gap-lg">
      <div className="flex flex-wrap gap-lg">
        <ExplainReadout
          metric="candidate_funnel"
          label="Reviewed"
          value={reviewed.toLocaleString()}
        />
        <ExplainReadout
          metric="taste_of_yes"
          label="Accepted"
          value={taste_of_yes.accepted_count.toLocaleString()}
        />
      </div>

      {source_efficacy.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="source_efficacy">
            <span className="micro-caps text-text-muted">
              Source efficacy — accept rate
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {source_efficacy.map((s) => (
              <BarRow
                key={s.source}
                label={s.source}
                fraction={s.accept_rate / maxRate}
                value={`${(s.accept_rate * 100).toFixed(0)}%`}
                accent
              />
            ))}
          </div>
        </div>
      )}

      {taste_of_yes.axes.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="taste_of_yes">
            <span className="micro-caps text-text-muted">
              The sound of yes — accepted vs rejected
            </span>
          </Explain>
          <DeltaStrip axes={taste_of_yes.axes} />
        </div>
      )}

      {per_artist_affinity.loved.length > 0 && (
        <div className="flex flex-col gap-xs">
          <Explain metric="per_artist_affinity">
            <span className="micro-caps text-text-muted">
              Artists you keep saying yes to
            </span>
          </Explain>
          <div className="flex flex-col gap-2xs">
            {per_artist_affinity.loved.slice(0, 5).map((a) => (
              <NameLine
                key={a.artist}
                title={a.artist}
                trailing={`${(a.accept_rate * 100).toFixed(0)}% of ${a.reviews}`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
