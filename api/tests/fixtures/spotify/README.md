# Spotify fixtures

Every file here carries a top-level `"synthetic"` flag:

- `"synthetic": true` — hand-authored against the documented Spotify Web API
  schemas (Phase 0's authed smoke run had not happened when these were written).
  Re-validate against recorded responses once the authed smoke run lands, then
  flip the flag.
- `"synthetic": false` — verbatim recorded response.

Playlist-entry fixtures also carry an `"endpoint_shape"` flag (2026-07 docs
sweep: `GET/POST/DELETE/PUT /playlists/{id}/tracks` is deprecated in favour of
`/items`, whose entries key the track on `item` with `track` as a deprecated
alias):

- `"endpoint_shape": "items"` — the current `/playlists/{id}/items` response
  shape (`playlist_items_page*.json`).
- `"endpoint_shape": "tracks-deprecated"` — the legacy `/playlists/{id}/tracks`
  shape (`playlist_tracks_page*.json`). Kept because the client still falls
  back to this path for followed-but-unowned playlists, which 403 on `/items`.

`token_refresh_invalid_grant.json` is the token endpoint's 400 body when a
refresh token ages out of Spotify's 6-month authorization lifetime.

The flags are extra top-level keys on otherwise schema-faithful payloads;
pydantic parsing ignores them.
