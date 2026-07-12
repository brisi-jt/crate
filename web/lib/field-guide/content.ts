import type { FieldGuideMode } from "@/lib/store/ui";

export interface FieldGuideStats {
  /** Playlist graph */
  playlistCount?: number;
  edgeCount?: number;
  subsetCount?: number;
  /** Track field */
  trackCount?: number;
  clusterCount?: number;
  ari?: number | null;
  /** Artist galaxy */
  artistsShown?: number;
  artistsTotal?: number;
  bridgeCount?: number;
  /** Frontier panel */
  territoryCount?: number;
  frontierCount?: number;
  /** Insights dock */
  enrichedTracks?: number;
  archetype?: string;
}

export interface FieldGuideLine {
  /** Short label — displayed in micro-caps above the line */
  label: string;
  /** Full natural-language reading */
  body: string;
}

export interface FieldGuideContent {
  title: string;
  summary: string;
  legend: FieldGuideLine[];
  prompts: string[];
}

function formatNum(n: number | undefined): string {
  return n !== undefined ? n.toLocaleString() : "—";
}

export function fieldGuideContent(
  mode: FieldGuideMode,
  stats: FieldGuideStats,
): FieldGuideContent {
  switch (mode) {
    case "playlists": {
      const pl = formatNum(stats.playlistCount);
      const edges = formatNum(stats.edgeCount);
      const subsets = stats.subsetCount ?? 0;

      const legend: FieldGuideLine[] = [
        {
          label: "Node",
          body: "One playlist. Size = track count. Color encodes sound: hue shifts organic ↔ electronic, vividness = energy, brightness = mood.",
        },
        {
          label: "Edge",
          body: "Shared tracks between two playlists. Wider = more overlap.",
        },
        {
          label: "Orbit ring",
          body: "A dashed ring with an inset satellite means every track in the smaller list lives in the larger one — a full subset.",
        },
      ];

      const prompts = [
        "Families and bridges — tight clusters share a sound; lone connectors are your cross-genre traffic controllers.",
        "Similar color, no edge — sonic twins that have never shared a track. Worth cross-pollinating.",
        "Isolated nodes — playlists with no shared tracks. Orphaned curation.",
      ];

      if (subsets > 0) {
        prompts.unshift(
          `${subsets} subset ${subsets === 1 ? "pair" : "pairs"} — the orbit ring means every track in the smaller list lives in the larger one too.`,
        );
      }

      return {
        title: "Playlist graph",
        summary: `${pl} playlists · ${edges} edges${subsets > 0 ? ` · ${subsets} subset ${subsets === 1 ? "pair" : "pairs"}` : ""}`,
        legend,
        prompts,
      };
    }

    case "tracks": {
      const tracks = formatNum(stats.trackCount);
      const clusters = formatNum(stats.clusterCount);
      const ariStr =
        stats.ari !== undefined && stats.ari !== null
          ? `ARI ${stats.ari.toFixed(2)}`
          : null;

      const legend: FieldGuideLine[] = [
        {
          label: "Point",
          body: "One track at its position in sound-space. UMAP projects acoustic features into 2D: nearby points sound similar.",
        },
        {
          label: "Color",
          body: "Acoustic mapping: hue = character (organic ↔ electronic), vividness = energy, brightness = mood.",
        },
        {
          label: "Hull",
          body: "Density clusters the math found on its own — no playlist labels, no human curation. Toggle CLUSTERS to show/hide.",
        },
      ];

      const prompts = [
        "Manual curation vs natural clusters — do your playlist territories match what the math grouped? Tight overlap means your ear and the algorithm agree.",
        "Outliers far from their playlist's hull — tracks that don't quite fit where you put them.",
        "Empty regions = taste gaps. The Frontier can help you fill them.",
      ];

      return {
        title: "Track field",
        summary: `${tracks} tracks · ${clusters} clusters${ariStr ? ` · ${ariStr}` : ""}`,
        legend,
        prompts,
      };
    }

    case "artists": {
      const shown = formatNum(stats.artistsShown);
      const total = formatNum(stats.artistsTotal);
      const bridgeStr =
        stats.bridgeCount !== undefined
          ? ` · ${stats.bridgeCount} bridging`
          : "";

      const legend: FieldGuideLine[] = [
        {
          label: "Node",
          body: "One artist. Color = sound of their tracks; size = co-appearance reach across your playlists.",
        },
        {
          label: "Solid edge",
          body: "Co-curated: these artists share at least one playlist in your library.",
        },
        {
          label: "Dashed edge",
          body: "External similarity from Last.fm — the world links them, whether or not you do.",
        },
      ];

      const prompts = [
        "Connective-tissue artists — high degree in both solid and dashed means they bridge worlds in your library.",
        "Pin two playlists to isolate the artists bridging them — the connective tissue between two crates.",
        "Dashed without solid — the world links them, you don't. Yet.",
      ];

      return {
        title: "Artist galaxy",
        summary:
          stats.artistsTotal !== undefined &&
          stats.artistsShown !== undefined &&
          stats.artistsShown < stats.artistsTotal
            ? `${shown} of ${total} artists shown${bridgeStr}`
            : `${shown} artists${bridgeStr}`,
        legend,
        prompts,
      };
    }

    case "frontier": {
      const territory = formatNum(stats.territoryCount);
      const frontier = formatNum(stats.frontierCount);

      const legend: FieldGuideLine[] = [
        {
          label: "Territory",
          body: "Genres you hold — ranked by how much of your library lives there.",
        },
        {
          label: "Frontier",
          body: "Adjacent genres you barely touch. Score = how strongly your borders point there.",
        },
        {
          label: "Seed",
          body: "Sends a frontier genre's exemplar artists to the deck for auditioning.",
        },
      ];

      return {
        title: "Frontier",
        summary: `${territory} territory · ${frontier} frontier`,
        legend,
        prompts: [],
      };
    }

    case "insights": {
      const enriched = formatNum(stats.enrichedTracks);
      const archetype = stats.archetype;

      const legend: FieldGuideLine[] = [
        {
          label: "Fingerprint",
          body: "Your library's mean sound — nine features at their library percentiles. The filled shape is your centroid color.",
        },
        {
          label: "Signatures",
          body: "Camelot keys, mood field, tempo and feature distributions — all from features crate computes itself, alive here and nowhere else.",
        },
        {
          label: "Archaeology",
          body: "Your curation history as a geological core, plus the playlists gone dormant.",
        },
      ];

      return {
        title: "Insights",
        summary: archetype
          ? `${archetype} · ${enriched} enriched`
          : `${enriched} enriched`,
        legend,
        prompts: [],
      };
    }
  }
}
