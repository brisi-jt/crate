# Spotify fixtures

Every file here carries a top-level `"synthetic"` flag:

- `"synthetic": true` — hand-authored against the documented Spotify Web API
  schemas (Phase 0's authed smoke run had not happened when these were written).
  Re-validate against recorded responses once the authed smoke run lands, then
  flip the flag.
- `"synthetic": false` — verbatim recorded response.

The flag is an extra top-level key on an otherwise schema-faithful payload;
pydantic parsing ignores it.
