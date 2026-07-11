# Enrichment fixtures

Same convention as `spotify/`: every file carries a top-level `"synthetic"`
flag.

- `reccobeats/` — `"synthetic": false`: verbatim recorded responses from the
  Phase 0 live probe (`thoughts/shared/research/phase0-fixtures/`).
- `lastfm/`, `musicbrainz/`, `freqblog/` — `"synthetic": true`: hand-authored
  against each service's documented response schema. Re-validate against
  recorded responses once live enrichment runs (needs a synced library and,
  for Last.fm/FreqBlog, API keys), then flip the flag.

The flag is an extra top-level key on an otherwise schema-faithful payload;
pydantic parsing ignores it.
