"use client";

import { Explain } from "@/components/explain/explain";
import type { GenreShare, RarestGenre } from "@/lib/api/schemas";
import { useUiStore } from "@/lib/store/ui";

interface TerritorySectionProps {
  genreShares: GenreShare[];
  rarest: RarestGenre[];
  meanRarity: number;
}

/**
 * TERRITORY — a compact genre reading: top genres by library share and the
 * rarest genres you hold (enao_rank-derived obscurity). The full atlas
 * territory/frontier reading lives in the FRONTIER panel — this links out to
 * it rather than duplicating the map.
 */
export function TerritorySection({
  genreShares,
  rarest,
  meanRarity,
}: TerritorySectionProps) {
  const openFrontier = useUiStore((s) => s.openFrontier);
  const maxShare = genreShares.reduce((m, g) => Math.max(m, g.share), 0);

  return (
    <div className="flex flex-col gap-lg">
      <section className="flex flex-col gap-xs">
        <span className="micro-caps text-text-muted">
          Top genres — by library share
        </span>
        {genreShares.length === 0 ? (
          <span className="micro-caps text-text-muted">NO GENRES MATCHED</span>
        ) : (
          <div className="flex flex-col gap-2xs">
            {genreShares.slice(0, 10).map((g) => (
              <div key={g.genre} className="flex items-center gap-sm">
                <span className="w-[150px] truncate text-sm text-text-primary">
                  {g.genre}
                </span>
                <div className="h-[4px] flex-1 rounded-xs bg-surface-2">
                  <div
                    className="h-full rounded-xs bg-border-strong"
                    style={{
                      width: `${Math.max(2, (g.share / (maxShare || 1)) * 100)}%`,
                    }}
                  />
                </div>
                <span className="data-readout w-[48px] text-right text-micro text-text-muted">
                  {(g.share * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-xs">
        <div className="flex items-baseline gap-sm">
          <Explain metric="mean_rarity">
            <span className="micro-caps text-text-muted">
              Rarest genres — mean rarity {meanRarity.toFixed(2)}
            </span>
          </Explain>
        </div>
        {rarest.length === 0 ? (
          <span className="micro-caps text-text-muted">NO RARE GENRES</span>
        ) : (
          <div className="flex flex-col gap-2xs">
            {rarest.slice(0, 8).map((g) => (
              <div key={g.genre} className="flex items-center gap-sm">
                <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
                  {g.genre}
                </span>
                <span className="data-readout text-micro text-text-muted">
                  #{g.enao_rank} · {(g.rarity * 100).toFixed(0)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <button
        type="button"
        onClick={openFrontier}
        className="micro-caps self-start cursor-pointer text-text-secondary hover:text-text-primary"
      >
        OPEN FRONTIER — full atlas territory & unexplored edges →
      </button>
    </div>
  );
}
