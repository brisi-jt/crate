"use client";

import { FieldGuideCard } from "@/components/chrome/field-guide-card";
import { CoreSampleStrip } from "@/components/insights/core-sample-strip";
import { DormancyList } from "@/components/insights/dormancy-list";
import { EditionBand } from "@/components/insights/edition-band";
import { EraSection } from "@/components/insights/era-section";
import { ExtremesBoard } from "@/components/insights/extremes-board";
import { IdentitySection } from "@/components/insights/identity-section";
import { SonicSection } from "@/components/insights/sonic-section";
import { SurveySection } from "@/components/insights/survey-section";
import { TerritorySection } from "@/components/insights/territory-section";
import { useInsights } from "@/hooks/api/use-insights";
import { useMe } from "@/hooks/api/use-me";

/**
 * The INSIGHTS dock (640px wide) — the survey report (option A) with the
 * field-journal edition band on top (option B), fused on one page. Sections
 * collapse and lazily render their viz; everything reads from GET /v1/insights.
 */
export function InsightsPanelContent() {
  const insights = useInsights();
  const me = useMe();

  if (insights.isPending) {
    return (
      <span className="micro-caps text-text-muted">
        COMPILING THE SURVEY · READING THE WHOLE LIBRARY
      </span>
    );
  }

  if (insights.isError || !insights.data) {
    return (
      <div className="flex flex-col items-start gap-xs">
        <span className="micro-caps text-danger">SURVEY UNAVAILABLE</span>
        <button
          type="button"
          onClick={() => insights.refetch()}
          className="micro-caps cursor-pointer text-text-secondary underline hover:text-text-primary"
        >
          Retry
        </button>
      </div>
    );
  }

  const data = insights.data;
  const {
    coverage,
    taste_identity,
    sonic_signatures,
    archaeology,
    eras,
    extremes,
  } = data;

  if (coverage.enriched_tracks === 0) {
    return (
      <div className="flex flex-col gap-sm">
        <span className="micro-caps text-text-muted">SURVEY PENDING</span>
        <p className="max-w-[56ch] text-sm text-text-secondary">
          The survey reads your enriched library. None of your{" "}
          {coverage.total_tracks.toLocaleString()} tracks carry acoustic
          features yet — sync and let enrichment run, then the fingerprint and
          signatures fill in.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-lg">
      <FieldGuideCard
        mode="insights"
        variant="inline"
        stats={{
          enrichedTracks: coverage.enriched_tracks,
          archetype: taste_identity.typology.archetype,
        }}
      />

      <EditionBand />

      <div className="flex flex-col gap-lg">
        <SurveySection
          title="TASTE IDENTITY"
          meta={taste_identity.typology.archetype.toUpperCase()}
        >
          <IdentitySection identity={taste_identity} coverage={coverage} />
        </SurveySection>

        <SurveySection
          title="SONIC SIGNATURES"
          meta={`${sonic_signatures.camelot.length} KEYS`}
        >
          <SonicSection sonic={sonic_signatures} />
        </SurveySection>

        <SurveySection
          title="COLLECTION ARCHAEOLOGY"
          meta={`${archaeology.abandoned_playlists.length} DORMANT`}
        >
          <div className="flex flex-col gap-lg">
            <div className="flex flex-col gap-2xs">
              <span className="micro-caps text-text-muted">
                Adds over time — core sample
              </span>
              <CoreSampleStrip adds={archaeology.adds_over_time} />
            </div>
            <div className="flex flex-col gap-xs">
              <span className="micro-caps text-text-muted">
                Abandoned playlists — dustiest first
              </span>
              <DormancyList playlists={archaeology.abandoned_playlists} />
            </div>
          </div>
        </SurveySection>

        <SurveySection
          title="ERA"
          meta={
            eras.center_of_gravity !== null
              ? `CoG ${eras.center_of_gravity}`
              : undefined
          }
        >
          <EraSection eras={eras} birthYear={me.data?.birth_year ?? null} />
        </SurveySection>

        <SurveySection title="TERRITORY">
          <TerritorySection
            genreShares={taste_identity.genre_shares}
            rarest={taste_identity.genre_rarity.rarest}
            meanRarity={taste_identity.genre_rarity.mean_rarity}
          />
        </SurveySection>

        <SurveySection title="ODDITIES" meta={`${extremes.length} RECORDS`}>
          <ExtremesBoard extremes={extremes} />
        </SurveySection>
      </div>
    </div>
  );
}
