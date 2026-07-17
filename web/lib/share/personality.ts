/**
 * The "crate DNA" personality label — a short, tasteful phrase derived purely
 * from the library's dominant sound and top genres. No horoscope, no cringe:
 * two mood words picked from a small curated grid, an obscurity qualifier, and
 * (when present) a light genre flavour. Fully deterministic.
 */

export interface PersonalityInput {
  /** Library-mean percentiles, 0..1. */
  energy: number;
  valence: number;
  acousticness: number;
  danceability: number;
  /** Library obscurity, 0 = mainstream … 1 = niche (F3 library score). */
  obscurity: number;
  /** Dominant genres, most-present first. */
  topGenres: string[];
}

/** low | mid | high band for a 0..1 value. */
function band(v: number): 0 | 1 | 2 {
  if (v < 0.34) return 0;
  if (v < 0.67) return 1;
  return 2;
}

/**
 * The mood noun, indexed by [valence band][energy band]. Rows = mood (dark →
 * bright), columns = energy (still → kinetic). Warm on the diagonal, honest at
 * the corners.
 */
const MOOD_GRID: string[][] = [
  // valence low (brooding)
  ["Dusk Drift", "Shadow Pulse", "Brooding Kinetic"],
  // valence mid (level)
  ["Hushed Room", "Even Keel", "Rolling Current"],
  // valence high (bright)
  ["Sunlit Calm", "Bright Motion", "Radiant Kinetic"],
];

/** An obscurity-keyed prefix. */
function obscurityQualifier(obscurity: number): string {
  const b = band(obscurity);
  if (b === 2) return "Deep-cut";
  if (b === 0) return "Chart-open";
  return "Wide-net";
}

/** A single acoustic flavour word, only when acousticness is decisive. */
function textureWord(acousticness: number): string | null {
  const b = band(acousticness);
  if (b === 2) return "organic";
  if (b === 0) return "synthetic";
  return null;
}

/**
 * Build the label: "<Obscurity> <Mood>" plus an optional trailing texture,
 * capped so it always reads as a tight identity phrase.
 */
export function personalityLabel(input: PersonalityInput): string {
  const mood = MOOD_GRID[band(input.valence)][band(input.energy)];
  const qualifier = obscurityQualifier(input.obscurity);
  const texture = textureWord(input.acousticness);

  const core = `${qualifier} ${mood}`;
  const label = texture ? `${core}, ${texture}` : core;

  // Safety clamp — the grid guarantees this, but never ship an overlong phrase.
  return label.length > 48 ? label.slice(0, 48).trimEnd() : label;
}
