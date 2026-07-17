/**
 * The central metric glossary — one source of truth for every "what is this /
 * how is it computed / where does it come from" explanation in the app.
 *
 * Keyed by a stable metric reference (see refs.ts). The same key resolves the
 * same explanation everywhere it appears, so a term explained on the insights
 * page reads identically on a canvas or in the glossary index. Prose is written
 * for a brand-new user: plain language, no internal vocabulary.
 */

import { REFERENCED_METRICS } from "./refs";

export interface ExplainEntry {
  /** The human name of the thing, e.g. "Genre entropy". */
  term: string;
  /** One plain sentence: what it is. */
  what: string;
  /** The formula or algorithm, in field-manual voice. */
  how: string;
  /** The tables or providers it comes from. */
  source: string;
  /** Optional unit hint, e.g. "bits", "percentile", "BPM". */
  unit?: string;
}

export const GLOSSARY: Record<string, ExplainEntry> = {
  // ── Playlist graph ──────────────────────────────────────────────────────
  acoustic_color: {
    term: "Acoustic colour",
    what: "The colour of every dot is its sound, not decoration.",
    how: "Hue runs organic (warm) to electronic (cool), colour intensity tracks energy, and lightness tracks how upbeat it feels. Similar sound means similar colour.",
    source:
      "Audio traits from ReccoBeats and Essentia, turned into your library's own percentiles.",
  },
  node_size: {
    term: "Playlist size",
    what: "A playlist's dot is bigger when it holds more tracks.",
    how: "Radius scales with the number of tracks in the playlist.",
    source: "Your synced playlists and their tracks.",
  },
  edge_width: {
    term: "Shared-track link",
    what: "A line between two playlists means they share tracks; thicker means more.",
    how: "Line width scales with how many tracks the two playlists have in common.",
    source: "Playlist membership across your library.",
  },
  orbit_ring: {
    term: "Contained-in ring",
    what: "A dashed ring means this playlist sits almost entirely inside a larger one.",
    how: "Drawn when at least ninety percent of its tracks also appear in the larger playlist.",
    source: "Playlist membership across your library.",
  },
  top_overlap: {
    term: "Strongest overlap",
    what: "The one playlist that shares the most tracks with this one.",
    how: "The single strongest shared-track link touching this playlist, and how many tracks it shares.",
    source: "Playlist membership across your library.",
  },
  features_coverage: {
    term: "Sound coverage",
    what: "How many of a playlist's tracks have their sound analysed yet.",
    how: "A count of enriched tracks out of the total; zero means nothing here has audio traits yet.",
    source: "Audio-trait enrichment from ReccoBeats and Essentia.",
  },

  // ── Track field ─────────────────────────────────────────────────────────
  umap: {
    term: "Similarity map",
    what: "A flattened map where tracks that sound alike sit close together.",
    how: "A dimension-reduction layout places each track by its sound. The axes carry no meaning on their own — only nearness does.",
    source: "Audio traits from ReccoBeats and Essentia.",
  },
  cluster_id: {
    term: "Cluster",
    what: "A group of tracks the maths found to sound alike, with no playlist told to it.",
    how: "A density-based grouping finds pockets of similar tracks on the similarity map.",
    source: "Audio traits from ReccoBeats and Essentia.",
  },
  noise: {
    term: "Unclustered",
    what: "A track that fits no dense group — a loner on the map.",
    how: "The grouping marks a track as noise when it has no close-enough neighbours to belong anywhere.",
    source: "Audio traits from ReccoBeats and Essentia.",
  },
  ari: {
    term: "Ear-vs-maths agreement",
    what: "How well the sound groups line up with how you actually filed your tracks.",
    how: "A score from minus one to one comparing the found clusters against your playlists. Higher means your ear and the maths agree.",
    source: "Found clusters compared against your playlist filing.",
    unit: "-1 to 1",
  },

  // ── Artist galaxy ───────────────────────────────────────────────────────
  bridging_artists: {
    term: "Bridging artists",
    what: "Artists that two of your playlists both lean on.",
    how: "Artists whose tracks appear in more than one of the playlists you have pinned.",
    source: "Playlist membership and artist credits.",
  },
  co_curated_edge: {
    term: "Co-curated link",
    what: "A solid line means two artists share space in your playlists.",
    how: "Drawn when both artists have tracks living in the same playlists you curate.",
    source: "Playlist membership and artist credits.",
  },
  similarity_edge: {
    term: "Similar-artist link",
    what: "A dashed line means two artists are considered alike by listeners.",
    how: "Drawn from listener-based similarity, separate from how you filed them.",
    source: "Artist similarity from Last.fm.",
  },
  artist_reach: {
    term: "Artist reach",
    what: "A bigger artist dot means the artist spans more of your playlists.",
    how: "Size scales with how many of your playlists hold this artist.",
    source: "Playlist membership and artist credits.",
  },

  // ── Listening deck ──────────────────────────────────────────────────────
  percentile: {
    term: "Percentile",
    what: "Where a track sits against the rest of your library on one trait.",
    how: "The percent of your enriched tracks this track scores above on that trait. Fifty is the middle of your catalogue.",
    source: "Your library's own distribution of that audio trait.",
    unit: "percentile",
  },
  profile_tick: {
    term: "Playlist target",
    what: "A tick marking where the target playlist typically sits on this trait.",
    how: "The middle value of the target playlist's tracks on that trait.",
    source: "The target playlist's tracks and their audio traits.",
  },

  // ── Frontier ────────────────────────────────────────────────────────────
  territory: {
    term: "Territory",
    what: "The genres you already hold.",
    how: "Genres present in your library, weighted by how much of it they cover.",
    source: "Artist genres matched to your library via Every Noise at Once.",
  },
  frontier: {
    term: "Frontier",
    what: "Genres next door to yours that you have barely touched.",
    how: "Genres adjacent to your territory with little or no presence yet.",
    source: "Artist genres matched to your library via Every Noise at Once.",
  },
  presence: {
    term: "Presence",
    what: "How much of a genre you hold, relative to your strongest genre.",
    how: "Your weight in that genre divided by your weight in your top genre, so the bar reads as a share.",
    source: "Artist genres weighted across your library.",
  },
  atlas: {
    term: "Genre atlas",
    what: "The map of nearly fifteen hundred genres your library is placed against.",
    how: "Each of your artists is matched onto a large public genre map to locate your taste.",
    source: "The Every Noise at Once genre atlas.",
  },
  matched_artists: {
    term: "Matched artists",
    what: "Your artists that were found on the genre atlas.",
    how: "Artists matched by name onto the public atlas so their genres can be counted.",
    source: "Your artists matched to Every Noise at Once.",
  },

  // ── Radio ───────────────────────────────────────────────────────────────
  harmonic_flow: {
    term: "Harmonic flow",
    what: "The running order is arranged so neighbouring tracks blend, like a DJ set.",
    how: "Tracks are ordered by musical key and tempo so each one leads smoothly into the next.",
    source: "Key and tempo from audio-trait enrichment.",
  },
  discovery_ratio: {
    term: "Discovery rate",
    what: "How often a fresh, unfamiliar track is slipped into the run.",
    how: "Roughly one in five picks is a track from outside your library, chosen to stay close to the seed.",
    source: "Recommendations from Last.fm and ReccoBeats.",
  },

  // ── Ops log ─────────────────────────────────────────────────────────────
  op_status: {
    term: "Operation status",
    what: "Whether an edit fully landed, partly landed, or was undone.",
    how: "Applied means every change went through; partial means some playlists failed; undone means the edit was reversed.",
    source: "The journal of changes you have made.",
  },
  dedupe: {
    term: "De-duplicate",
    what: "Removing repeats of the same recording from a playlist.",
    how: "Duplicate recordings are matched by their industry recording code and the extras are removed.",
    source: "Track recording codes across the playlist.",
  },

  // ── Insights: taste identity ────────────────────────────────────────────
  genre_entropy: {
    term: "Genre entropy",
    what: "How spread out your taste is across genres, as a measure of variety.",
    how: "A spread score over your genre weights, in bits — higher means your listening is more varied.",
    source: "Artist genres from Every Noise at Once, matched to your artists.",
    unit: "bits",
  },
  effective_genres: {
    term: "Effective genres",
    what: "The variety score restated as a rough count of genres you really live in.",
    how: "Two raised to your genre-spread score, giving an intuitive number of genres.",
    source: "Artist genres from Every Noise at Once, matched to your artists.",
  },
  gs_score: {
    term: "Acoustic sprawl",
    what: "Whether you are a specialist with one sound or a generalist across many.",
    how: "The average distance of your tracks from your library's centre in nine sound traits, scaled from zero (one narrow sound) to one (all over the place).",
    source: "Nine audio traits per track, as your library's percentiles.",
    unit: "0 to 1",
  },
  mean_rarity: {
    term: "Mean rarity",
    what: "How off-the-beaten-path your genres are on average.",
    how: "The average genre rank across your library, where a higher rank means a more obscure genre.",
    source: "Genre ranks from Every Noise at Once.",
  },
  fingerprint: {
    term: "Sound fingerprint",
    what: "A nine-spoke shape summarising your library's average sound.",
    how: "Each spoke is your library's middle percentile on one audio trait.",
    source: "Nine audio traits per track, as your library's percentiles.",
  },
  archetype_axes: {
    term: "Archetype axes",
    what: "The three dials behind your taste label: breadth, sprawl, and rarity.",
    how: "Each dial is a zero-to-one score; together they place you into a named listener archetype.",
    source: "Your genre spread, acoustic sprawl, and mean rarity.",
  },

  // ── Insights: sonic signatures ──────────────────────────────────────────
  camelot: {
    term: "Camelot wheel",
    what: "A DJ's key wheel showing which musical keys your library favours.",
    how: "Each track's key is placed on the wheel; the tint of each wedge is its average mood.",
    source: "Musical key and mood from audio-trait enrichment.",
  },
  mood_quadrants: {
    term: "Mood grid",
    what: "Your library laid out by energy against mood.",
    how: "Energy runs low to high across, mood runs sombre to bright up, and each cell is coloured by the sound that lands there.",
    source: "Energy and mood traits per track.",
  },
  tempo_spine: {
    term: "Tempo spine",
    what: "The spread of your library's tempos in beats per minute.",
    how: "Raw beats per minute per track, bucketed — this one is real tempo, not a percentile.",
    source: "Tempo from audio-trait enrichment.",
    unit: "BPM",
  },
  ridgelines: {
    term: "Ridgelines",
    what: "The shape of how each audio trait is distributed, not just its average.",
    how: "Each trait is split into twenty buckets and drawn as a ridge, so you see the whole shape.",
    source: "Nine audio traits per track.",
  },

  // ── Insights: archaeology / era ─────────────────────────────────────────
  core_sample: {
    term: "Core sample",
    what: "A cross-section of your library by when tracks were added, like rock strata.",
    how: "Tracks are stacked by the date you added them; a grey band marks adds not yet sound-analysed.",
    source: "The date each track was added, and enrichment status.",
  },
  dormancy: {
    term: "Dormancy",
    what: "A playlist you have not touched in a long while.",
    how: "Flagged when nothing has been added to the playlist for six months.",
    source: "The last time each playlist changed.",
  },
  center_of_gravity: {
    term: "Centre of gravity",
    what: "The single release year your library leans on most.",
    how: "The most common release year among your tracks — the peak year, not an average.",
    source: "Track release years.",
    unit: "year",
  },
  taste_freeze: {
    term: "Coming-of-age window",
    what: "The band of years thought to shape a listener's taste for life.",
    how: "Roughly ages sixteen to twenty-four, drawn from your birth year onward.",
    source: "Your birth year and track release years.",
  },

  // ── Library stats / bulk ops ────────────────────────────────────────────
  split_merge_hints: {
    term: "Split / merge hints",
    what: "Nudges to break a sprawling playlist apart or fold two similar ones together.",
    how: "Split hints flag playlists spanning several sound clusters; merge hints flag playlists that heavily overlap.",
    source: "Sound clusters and shared-track overlap.",
  },
  calibration_drift: {
    term: "Calibration drift",
    what: "How much your library's sound spread has shifted over time.",
    how: "The change in the low and high ends of your trait distributions between syncs.",
    source: "Your library's trait distribution across syncs.",
  },

  // ── Triage ──────────────────────────────────────────────────────────────
  triage_source: {
    term: "Triage source",
    what: "The pile of songs you are filing from — a chosen playlist or your Liked Songs.",
    how: "Pick a playlist to work through it in order, or Liked Songs to work through saves.",
    source: "Your playlists and saved tracks.",
  },
  orphan_filter: {
    term: "Orphan filter",
    what: "Limits the queue to saved songs that live in few or no playlists.",
    how: "Keeps only tracks that appear in at most the chosen number of your playlists; zero means saves in no playlist at all.",
    source: "Your saved tracks and playlist membership.",
  },
  sonic_fit: {
    term: "Sonic fit",
    what: "How closely a song's sound matches a playlist's typical sound.",
    how: "The nearness of the song to the playlist's average sound, with the traits that agree named.",
    source: "Audio traits per track, as your library's percentiles.",
  },
  artist_overlap: {
    term: "Artist overlap",
    what: "Whether the song's artist or genre is already at home in a playlist.",
    how: "A count of tracks by the same artist, or in the same genre, already in that playlist.",
    source: "Artist credits and genres across your playlists.",
  },
  placement_history: {
    term: "Placement history",
    what: "Where songs that sound like this one usually end up.",
    how: "The playlists that the nearest already-filed songs on the similarity map were filed into.",
    source: "Your past filing and audio-trait nearness.",
  },
  vibe_match: {
    term: "Name and vibe match",
    what: "Whether a playlist's name and description echo the song's genres.",
    how: "Overlap between words in the playlist name and description and the song's genre tags.",
    source: "Playlist names and descriptions against song genres and tags.",
  },
  suggestion_rank: {
    term: "Suggestion rank",
    what: "The overall standing of a suggested destination among the options.",
    how: "A blend of the four evidence signals, each shown separately so you can see why — never a single hidden score.",
    source:
      "Sonic fit, artist overlap, placement history, and name-vibe match.",
  },
  cluster_proposal: {
    term: "New-playlist suggestion",
    what: "A brand-new playlist idea grown from a pocket of similar songs in the queue.",
    how: "The queue is grouped by sound, and a dense group becomes a proposal with a suggested name and founding songs.",
    source: "Audio traits and genres of the songs in the queue.",
  },

  // ── Extended survey — play history ──────────────────────────────────────
  play_collect_gap: {
    term: "Play vs collect gap",
    what: "Songs you play far more, or far less, than how much you've filed them away.",
    how: "Your play counts set against how many of your playlists each track sits in, then the biggest mismatches either way.",
    source: "Your listening history and playlist membership.",
  },
  listening_clock: {
    term: "Listening clock",
    what: "When you actually listen — across the hours of the day and the days of the week.",
    how: "Every play is tallied by its hour and weekday, and the busiest hour is marked.",
    source: "Your listening history.",
  },
  rotation_velocity: {
    term: "Rotation velocity",
    what: "Whether you mostly replay fresh additions or dig through your deeper catalogue.",
    how: "The share of plays landing on tracks you added in the last three months.",
    source: "Your listening history and when tracks were added.",
    unit: "share",
  },
  context_mix: {
    term: "Play context mix",
    what: "Where your plays come from — a playlist, an album, an artist page, or a show.",
    how: "Each play carries what it was started from; those are counted and shown as shares.",
    source: "Your listening history.",
  },
  play_mood_by_hour: {
    term: "Mood by time of day",
    what: "How the energy and mood of what you play shift from morning to night.",
    how: "Plays are grouped into morning, afternoon, evening, and night, and the average energy and brightness of each is taken.",
    source: "Your listening history and per-track audio traits.",
  },
  deep_cuts_vs_hits: {
    term: "Deep cuts vs hits",
    what: "Whether your listening leans toward obscure tracks or well-filed favourites.",
    how: "Plays are split by how widely each track sits across your playlists; the obscure share is reported.",
    source: "Your listening history and playlist membership.",
    unit: "share",
  },

  // ── Extended survey — saved songs ───────────────────────────────────────
  liked_vs_playlist: {
    term: "Liked vs playlist sound",
    what: "How the sound of your Liked Songs differs from the sound of your playlists.",
    how: "The average of each audio trait across your likes, set against the same average across your playlist tracks, trait by trait.",
    source:
      "Your saved tracks and playlist tracks, as your library's percentiles.",
  },
  save_file_latency: {
    term: "Save-to-file time",
    what: "How long a liked song usually waits before you file it into a playlist.",
    how: "The median number of days from when a track was saved to when it first landed in a playlist.",
    source: "Your saved tracks and when tracks were added to playlists.",
    unit: "days",
  },
  unsave_churn: {
    term: "Unsave churn",
    what: "How much of what you save you later un-like.",
    how: "The share of all your saves that were later removed from Liked Songs.",
    source: "Your saved tracks, including removed ones.",
    unit: "share",
  },
  orphan_saves: {
    term: "Orphan saves",
    what: "Liked songs that live in none of your playlists — the inbox you forgot.",
    how: "Saved tracks that appear in no owned playlist are counted and listed.",
    source: "Your saved tracks and playlist membership.",
  },

  // ── Extended survey — suggestion feedback ───────────────────────────────
  source_efficacy: {
    term: "Source efficacy",
    what: "Which suggestion sources you actually accept from most often.",
    how: "For each source of suggested tracks, the share you accepted versus rejected.",
    source: "Your accept/reject decisions on suggested candidates.",
    unit: "accept rate",
  },
  taste_of_yes: {
    term: "The sound of yes",
    what: "How the songs you accept differ in sound from the ones you turn down.",
    how: "The average of each audio trait across accepted suggestions, set against the same across rejected ones.",
    source: "Your accept/reject decisions and per-track audio traits.",
  },
  per_artist_affinity: {
    term: "Per-artist affinity",
    what: "Artists you keep saying yes to, and ones you keep waving off.",
    how: "For artists you've judged at least twice, accepts versus rejects, ranked most-loved and most-declined.",
    source: "Your accept/reject decisions by artist.",
  },
  candidate_funnel: {
    term: "Suggestion funnel",
    what: "Where suggested songs sit in their journey — waiting, reviewed, accepted, or rejected.",
    how: "Every suggested candidate is counted by the stage it has reached.",
    source: "The suggestion queue and your decisions on it.",
  },

  // ── Extended survey — top items ─────────────────────────────────────────
  top_vs_library: {
    term: "Top tracks vs library",
    what: "How your most-played favourites sound compared with your whole collection.",
    how: "The average of each audio trait across your recent top tracks, set against the same across the full library.",
    source: "Your recorded top-tracks and per-track audio traits.",
  },
  affinity_churn: {
    term: "Affinity churn",
    what: "How much your top artists turn over from one reading to the next.",
    how: "The overlap between successive top-artist lists — high means steady, low means fast-changing.",
    source: "Your recorded top-artist readings over time.",
  },
  short_vs_long: {
    term: "Rising vs settled",
    what: "Which favourites are new obsessions and which are long-settled.",
    how: "Comparing your recent top artists with your long-run top artists: rising are only in the recent list, fading only in the long one, stable in both.",
    source: "Your short- and long-window top-artist readings.",
  },

  // ── Extended survey — radio ─────────────────────────────────────────────
  radio_keep_rate: {
    term: "Radio keep rate",
    what: "How much of what a generated radio session serves you actually keep.",
    how: "The share of radio tracks kept rather than skipped, overall and by the kind of seed the session grew from.",
    source: "Your radio sessions and kept/skipped decisions.",
    unit: "keep rate",
  },
  discovery_conversion: {
    term: "Discovery conversion",
    what: "How often the unfamiliar tracks slipped into radio actually land with you.",
    how: "The share of discovery tracks in your radio sessions that you kept.",
    source: "Your radio sessions and kept/skipped decisions.",
    unit: "share",
  },

  // ── Extended survey — curation journal ──────────────────────────────────
  curation_intensity: {
    term: "Curation intensity",
    what: "How busily you edit your library — pace, the mix of edits, and how often you undo.",
    how: "Edits per week, the split across kinds of edit, and the share of edits later undone.",
    source: "Your record of library edits.",
    unit: "edits / week",
  },
  bulk_algebra: {
    term: "Bulk operations",
    what: "Which whole-set moves you reach for — merging, subtracting, intersecting, and the like.",
    how: "Each bulk operation you've run is counted by kind.",
    source: "Your record of library edits.",
  },

  // ── Extended survey — cross-table ───────────────────────────────────────
  listened_vs_neglected: {
    term: "Listened vs neglected",
    what: "Which quiet playlists you still secretly play, and which are truly forgotten.",
    how: "Playlists you haven't added to in a while, crossed with whether their tracks still show up in your plays.",
    source:
      "Your playlists, when they were last touched, and your listening history.",
  },
  era_add_vs_release: {
    term: "Nostalgia waves",
    what: "Whether you add fresh releases or dig back into older years.",
    how: "For each year you were adding tracks, the median gap between a track's release year and when you filed it.",
    source: "When you added tracks and when those tracks were released.",
    unit: "years",
  },

  // ── Listening dashboard (F1) ───────────────────────────────────────────
  listening_rhythm: {
    term: "Listening rhythm",
    what: "The shape of your listening — how many plays, over how many tracks.",
    how: "A count of every recorded play and the number of distinct tracks behind them.",
    source:
      "Your play history — live captures plus any imported streaming history.",
  },
  listening_minutes: {
    term: "Minutes listened",
    what: "Roughly how long you've spent listening.",
    how: "The sum of each play's length. Live plays don't record a length, so those fall back to a typical track length and the figure is marked as an estimate.",
    source: "Your play history.",
    unit: "minutes",
  },
  listening_streaks: {
    term: "Listening streak",
    what: "How many days in a row you kept listening.",
    how: "The longest run of back-to-back calendar days with at least one play, and the run you're on now.",
    source: "Your play history.",
    unit: "days",
  },
  listening_clock_peak: {
    term: "Peak hour",
    what: "The hour of the day you listen the most.",
    how: "Plays are bucketed by hour of day; the fullest bucket is your peak.",
    source: "Your play history.",
  },

  // ── Obscurity (F3) ─────────────────────────────────────────────────────
  obscurity_library: {
    term: "Library obscurity",
    what: "How niche your whole library leans, from mainstream to deep-cut.",
    how: "Each track takes the rank of its most well-known genre; zero is mainstream, one is niche. The library score averages them.",
    source: "Genre ranks from the Every Noise at Once layer.",
  },
  obscurity_playlist: {
    term: "Playlist obscurity",
    what: "The same niche-versus-mainstream reading, for one playlist.",
    how: "The average obscurity of the playlist's tracks; a track with no ranked genre counts as fully niche.",
    source: "Genre ranks from the Every Noise at Once layer.",
  },

  // ── Taste drift (F5) ───────────────────────────────────────────────────
  taste_drift: {
    term: "Taste drift",
    what: "How far your sound today has moved from a past reading of your top tracks.",
    how: "Your current library's average sound is compared feature by feature against a past top-tracks reading; the overall distance and the feature that moved most are called out.",
    source: "Your current library and past recorded top-track readings.",
  },

  // ── Flow sequencer (F4) ────────────────────────────────────────────────
  flow_arc: {
    term: "Flow arc",
    what: "A suggested running order that smooths the ride between tracks.",
    how: "Tracks are re-ordered to ease energy, mood, and tempo jumps into a rising, falling, or peaking shape, while keeping the same artist from landing back to back.",
    source: "Self-derived tempo, energy, and mood, plus each track's artist.",
  },

  // ── Per-playlist quality (F6) ──────────────────────────────────────────
  quality_cohesion: {
    term: "Cohesion",
    what: "How tightly a playlist's tracks sit together in sound.",
    how: "The average spread between tracks in sound space, flipped so a tighter cluster scores higher.",
    source: "Self-derived audio traits.",
  },
  quality_uniqueness: {
    term: "Uniqueness",
    what: "How free of repeats a playlist is.",
    how: "One minus the share of duplicated tracks, counting both the same track twice and the same recording under a different id.",
    source: "Playlist membership and recording ids.",
  },
  quality_freshness: {
    term: "Freshness",
    what: "How recently the playlist was touched.",
    how: "A gentle decay on the time since its newest add, so long-dormant playlists score lower.",
    source: "When tracks were added to the playlist.",
  },
  quality_flow: {
    term: "Flow quality",
    what: "How smoothly a playlist already runs, front to back.",
    how: "The existing key and tempo flow reading, scaled to a zero-to-one score.",
    source: "Self-derived tempo and key.",
  },

  // ── Data providers ──────────────────────────────────────────────────────
  source_reccobeats: {
    term: "ReccoBeats",
    what: "An open source of per-track audio traits like energy and mood.",
    how: "Tracks are looked up and their audio traits stored for use across the app.",
    source: "The ReccoBeats open audio-features service.",
  },
  source_lastfm: {
    term: "Last.fm",
    what: "A listening community that supplies artist similarity and tags.",
    how: "Artist similarity and crowd tags are pulled in to enrich your artists and genres.",
    source: "The Last.fm music database.",
  },
  source_musicbrainz: {
    term: "MusicBrainz",
    what: "An open music encyclopedia used to identify recordings.",
    how: "Recordings are matched by their industry code so tracks can be linked and de-duplicated.",
    source: "The MusicBrainz open music database.",
  },
  source_deezer: {
    term: "Deezer previews",
    what: "The source of the short audio clips you hear on preview.",
    how: "A thirty-second preview is fetched so you can listen before filing.",
    source: "Deezer preview clips.",
  },
  source_enao: {
    term: "Every Noise at Once",
    what: "A map of nearly fifteen hundred genres your taste is placed against.",
    how: "Your artists are matched onto the map to locate and rank your genres.",
    source: "The Every Noise at Once genre atlas.",
  },
  source_essentia: {
    term: "Essentia",
    what: "An open audio-analysis engine behind some of your track traits.",
    how: "Audio is analysed to derive traits like key, tempo, and energy.",
    source: "The Essentia open audio-analysis library.",
  },
};

/** Resolve a metric ref to its entry, or null if the key is unknown. */
export function resolveExplain(metric: string): ExplainEntry | null {
  return GLOSSARY[metric] ?? null;
}

export interface GlossaryItem {
  ref: string;
  entry: ExplainEntry;
}

/**
 * Every glossary entry, sorted alphabetically by term — the browsable index
 * behind the glossary command.
 */
export function allGlossaryEntries(): GlossaryItem[] {
  return Object.entries(GLOSSARY)
    .map(([ref, entry]) => ({ ref, entry }))
    .sort((a, b) => a.entry.term.localeCompare(b.entry.term));
}

// Compile-time nudge: keep the referenced checklist and the glossary in step.
// (The runtime completeness test in glossary.test.ts is the real gate.)
void REFERENCED_METRICS;
