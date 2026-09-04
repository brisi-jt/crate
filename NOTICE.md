# Notices & Attribution

crate is released under the [MIT License](./LICENSE). This file records the
third-party services it draws on and the disclaimers that go with them.

## Spotify

crate is an independent, unofficial project. It is **not affiliated with,
endorsed by, or sponsored by Spotify**. It uses the Spotify Web API under
Spotify's developer terms, and references Spotify only nominatively (to name
the service it connects to); no Spotify trademarks or logos are used as
branding.

Note on scope: since 2026, Spotify grants new apps no access to the
audio-features, recommendations, or related-artists endpoints, and caps
development-mode apps at five users. crate is built for personal use within
those limits — all listening intelligence is derived from the open data
sources below rather than from Spotify's (now-restricted) analysis endpoints.

## Open data sources

crate's taste analysis is assembled from several independent providers. Each
is queried within its published terms and rate-limit etiquette.

- **MusicBrainz** (`musicbrainz.org`) — recording/artist identity and
  metadata. Core MusicBrainz data is released under CC0; the API is used with
  a descriptive User-Agent and polite request pacing.
- **Last.fm** (`ws.audioscrobbler.com`) — artist similarity and tags, used for
  genre/neighbour signals. Requires a personal API key (optional).
- **ReccoBeats** (`api.reccobeats.com`) — audio-feature estimates keyed by
  track, a primary replacement for Spotify's withdrawn audio-features endpoint.
- **FreqBlog** (`api.freq.blog`) — a secondary audio-feature source, metered
  against a fixed monthly budget as a fallback when other sources miss a track.
- **Deezer** (`api.deezer.com`) — search plus 30-second preview clips, used
  under Deezer's API terms for local audio analysis when hosted feature
  sources have no coverage.
- **Every Noise at Once** / Glenn McDonald — the genre-space map that inspired
  crate's genre-coordinate model and informs genre-blended distance.

Trademarks and data referenced here remain the property of their respective
owners. Attribution here does not imply their endorsement of crate.

## Open-core boundary

The code in this repository is the open engine and is MIT-licensed. Any future
hosted or commercial offering built on top of it (for example, importing a
personal data export to run the same analysis) is a separate product layer and
is not part of this repository. Open-sourcing the engine does not surrender the
author's rights to build such a product.
