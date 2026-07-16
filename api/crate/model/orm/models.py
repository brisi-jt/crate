"""Persisted models.

Tables are created by hand-written Alembic migrations — keep these definitions
in step with migrations/versions/. The integration round-trip suite verifies
model ↔ migrated-schema agreement field by field.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field

from crate.model.enums import (
    BulkOperation,
    CandidateSource,
    CandidateStatus,
    CredentialStatus,
    DigestSection,
    FeatureSource,
    FeatureStatus,
    FeedbackAction,
    MutationOpType,
    MutationStatus,
    PlaylistSyncStatus,
    RadioItemFeedback,
    RadioItemKind,
    RadioSeedKind,
    SimilaritySource,
    SnapshotKind,
    SyncEventSource,
    SyncEventType,
    TagSource,
    TopItemKind,
    TopTimeRange,
)
from crate.model.orm.base import TimestampedModel, enum_column, utcnow


class User(TimestampedModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    clerk_user_id: str | None = Field(default=None, unique=True, max_length=64)
    spotify_user_id: str | None = Field(default=None, unique=True, max_length=64)
    # Supplied by the user (not from Spotify) to personalize the taste-freeze
    # reading — the 16-24 coming-of-age band overlays the era profile only when
    # this is set. Validated 1900..(current year - 13) at the API boundary.
    birth_year: int | None = Field(default=None)


class SpotifyCredential(TimestampedModel, table=True):
    """One Spotify connection per user; tokens are Fernet-encrypted at rest."""

    __tablename__ = "spotify_credentials"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True)
    refresh_token_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    access_token_encrypted: str | None = Field(default=None, sa_column=Column(Text))
    access_token_expires_at: datetime | None = Field(default=None)
    scope: str | None = Field(default=None, max_length=512)
    status: CredentialStatus = Field(
        default=CredentialStatus.active,
        sa_column=enum_column(CredentialStatus, nullable=False),
    )


class Playlist(TimestampedModel, table=True):
    __tablename__ = "playlists"
    __table_args__ = (UniqueConstraint("user_id", "spotify_id", name="uq_playlists_user_spotify"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    spotify_id: str = Field(max_length=64)
    name: str = Field(max_length=512)
    description: str | None = Field(default=None, sa_column=Column(Text))
    snapshot_id: str | None = Field(default=None, max_length=128)
    is_owned: bool = Field(default=True)
    # Set when a sync pass no longer sees the playlist on Spotify. The row and
    # its membership stay for event history.
    is_deleted: bool = Field(default=False)
    status: PlaylistSyncStatus = Field(
        default=PlaylistSyncStatus.pending,
        sa_column=enum_column(PlaylistSyncStatus, nullable=False),
    )
    last_synced_at: datetime | None = Field(default=None)


class Track(TimestampedModel, table=True):
    """Global catalog row — shared across users and playlists."""

    __tablename__ = "tracks"

    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str = Field(unique=True, max_length=64)
    isrc: str | None = Field(default=None, index=True, max_length=16)
    name: str = Field(max_length=512)
    # Ordered [{"spotify_id": ..., "name": ...}] as delivered by Spotify.
    artists: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    album_spotify_id: str | None = Field(default=None, max_length=64)
    album_name: str | None = Field(default=None, max_length=512)
    duration_ms: int | None = Field(default=None)
    # Album release date as Spotify reports it, backfilled from /v1/albums.
    # Precision records how much of the date Spotify knew: a "year" release
    # stores "1998", a "day" release "1998-06-30". release_year is the parsed
    # leading year, the spine of every decade / era / taste-freeze analytic.
    release_date: str | None = Field(default=None, max_length=10)
    release_date_precision: str | None = Field(default=None, max_length=5)
    release_year: int | None = Field(default=None, index=True)


class Artist(TimestampedModel, table=True):
    """Global catalog row; mbid is filled by the enrichment pipeline."""

    __tablename__ = "artists"

    id: int | None = Field(default=None, primary_key=True)
    spotify_id: str = Field(unique=True, max_length=64)
    name: str = Field(max_length=512)
    mbid: str | None = Field(default=None, max_length=64)
    # When the identity stage last attempted an MBID for this artist (even a
    # miss). Set on attempt so the un-resolvable long tail is not re-selected
    # every pass and the identity backlog drains; clear it (null) to re-attempt
    # after new ISRC-bearing tracks arrive. Mirrors TrackFeatures.preview_resolved's
    # "don't retry the hopeless" semantics.
    mbid_checked_at: datetime | None = Field(default=None)


class PlaylistTrack(TimestampedModel, table=True):
    """Playlist membership at the current sync; position is 0-based."""

    __tablename__ = "playlist_tracks"
    __table_args__ = (
        UniqueConstraint("playlist_id", "position", name="uq_playlist_tracks_position"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    playlist_id: int = Field(foreign_key="playlists.id", index=True)
    track_id: int = Field(foreign_key="tracks.id", index=True)
    position: int = Field()
    added_at: datetime | None = Field(default=None)


class SyncEvent(TimestampedModel, table=True):
    """Append-only history of observed and self-inflicted playlist changes."""

    __tablename__ = "sync_events"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    playlist_id: int = Field(foreign_key="playlists.id", index=True)
    # Null for playlist-level events (created/renamed/deleted/reordered).
    track_id: int | None = Field(default=None, foreign_key="tracks.id")
    event_type: SyncEventType = Field(sa_column=enum_column(SyncEventType, nullable=False))
    source: SyncEventSource = Field(
        default=SyncEventSource.sync,
        sa_column=enum_column(SyncEventSource, nullable=False),
    )
    observed_at: datetime = Field(default_factory=utcnow, index=True)
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class TrackFeatures(TimestampedModel, table=True):
    """Audio features for one track, from whichever source answered first.

    Feature values are Essentia-derived (ReccoBeats/FreqBlog), not
    Spotify-distributed — compare them through FeatureCalibration percentiles,
    never against Spotify-era absolute thresholds.
    """

    __tablename__ = "track_features"

    id: int | None = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="tracks.id", unique=True)
    energy: float | None = Field(default=None)
    valence: float | None = Field(default=None)
    danceability: float | None = Field(default=None)
    acousticness: float | None = Field(default=None)
    instrumentalness: float | None = Field(default=None)
    liveness: float | None = Field(default=None)
    speechiness: float | None = Field(default=None)
    tempo: float | None = Field(default=None)
    key: int | None = Field(default=None)
    mode: int | None = Field(default=None)
    loudness: float | None = Field(default=None)
    status: FeatureStatus = Field(
        default=FeatureStatus.present,
        sa_column=enum_column(FeatureStatus, nullable=False),
    )
    # Null while status is missing — no source has supplied values yet.
    source: FeatureSource | None = Field(
        default=None, sa_column=enum_column(FeatureSource, nullable=True)
    )
    # Raw local-DSP values before quantile mapping into the ReccoBeats space.
    # Only set when source is essentia; the mapped values live in the feature
    # columns above so every consumer ranks in one distribution.
    local_raw: dict[str, float] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # Local analysis needs a 30-second preview. Null = never looked for one,
    # True = found (and analyzed), False = no preview exists for this track.
    preview_resolved: bool | None = Field(default=None)
    fetched_at: datetime = Field(default_factory=utcnow)


class ArtistSimilarity(TimestampedModel, table=True):
    """Directed artist→artist similarity edge.

    The similar artist is stored by name (plus mbid when the source gives
    one); similar_artist_id is linked only when that artist exists in our
    catalog.
    """

    __tablename__ = "artist_similarities"
    __table_args__ = (
        UniqueConstraint(
            "artist_id", "similar_artist_name", "source", name="uq_artist_similarities_edge"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    artist_id: int = Field(foreign_key="artists.id", index=True)
    similar_artist_id: int | None = Field(default=None, foreign_key="artists.id")
    similar_artist_name: str = Field(max_length=512)
    similar_artist_mbid: str | None = Field(default=None, max_length=64)
    # Source-reported match strength, normalized to 0..1.
    weight: float = Field()
    source: SimilaritySource = Field(sa_column=enum_column(SimilaritySource, nullable=False))


class ArtistTag(TimestampedModel, table=True):
    """Descriptive tag on an artist (Last.fm folksonomy or ENAO genre)."""

    __tablename__ = "artist_tags"
    __table_args__ = (UniqueConstraint("artist_id", "tag", "source", name="uq_artist_tags_tag"),)

    id: int | None = Field(default=None, primary_key=True)
    artist_id: int = Field(foreign_key="artists.id", index=True)
    tag: str = Field(max_length=256)
    # Source-reported relevance (Last.fm count, 0..100).
    weight: float = Field()
    source: TagSource = Field(sa_column=enum_column(TagSource, nullable=False))


class Genre(TimestampedModel, table=True):
    """Genre from the Every Noise at Once dump."""

    __tablename__ = "genres"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, max_length=256)
    # Position in ENAO's popularity-ordered genre list (1 = most popular).
    enao_rank: int | None = Field(default=None)


class ArtistGenre(TimestampedModel, table=True):
    """Artist↔genre membership from the ENAO dump.

    Keyed by artist name (the dump has no Spotify IDs for artists);
    artist_id is linked when the name matches an artist in our catalog.
    Weight sums exemplar-list appearances and sub-genre tag counts, so it is
    comparable within a genre, not across genres.
    """

    __tablename__ = "artist_genres"
    __table_args__ = (
        UniqueConstraint("genre_id", "artist_name", name="uq_artist_genres_membership"),
    )

    id: int | None = Field(default=None, primary_key=True)
    genre_id: int = Field(foreign_key="genres.id", index=True)
    artist_name: str = Field(index=True, max_length=512)
    artist_id: int | None = Field(default=None, foreign_key="artists.id")
    weight: float = Field()


class FeatureCalibration(TimestampedModel, table=True):
    """Library-wide percentile anchors for one audio feature.

    Downstream analytics rank tracks against these percentiles instead of
    absolute values, because the feature distributions are Essentia's, not
    Spotify's.
    """

    __tablename__ = "feature_calibrations"

    id: int | None = Field(default=None, primary_key=True)
    feature: str = Field(unique=True, max_length=32)
    p10: float = Field()
    p50: float = Field()
    p90: float = Field()
    sample_size: int = Field()
    computed_at: datetime = Field(default_factory=utcnow)


class LocalDspCalibration(TimestampedModel, table=True):
    """Quantile mapping from local-DSP feature values into the ReccoBeats space.

    Fitted on the overlap set — tracks that have both a ReccoBeats value and a
    locally-analyzed preview — so the map corrects source bias, not repertoire
    bias. local_anchors[i] maps to target_anchors[i] by linear interpolation.
    """

    __tablename__ = "local_dsp_calibrations"

    id: int | None = Field(default=None, primary_key=True)
    feature: str = Field(unique=True, max_length=32)
    # Matched quantile grids: same length, both ascending.
    local_anchors: list[float] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    target_anchors: list[float] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    sample_size: int = Field()
    computed_at: datetime = Field(default_factory=utcnow)


class FreqBlogBudget(TimestampedModel, table=True):
    """Calls consumed against FreqBlog's monthly lookup allowance."""

    __tablename__ = "freqblog_budget"

    id: int | None = Field(default=None, primary_key=True)
    # Calendar month the counter covers, e.g. "2026-07".
    month: str = Field(unique=True, max_length=7)
    used: int = Field(default=0)


class ApiResponseCache(TimestampedModel, table=True):
    """Cached third-party API responses, keyed per source.

    Enrichment sources are heavily rate-limited; re-runs read from here
    instead of re-fetching.
    """

    __tablename__ = "api_response_cache"
    __table_args__ = (UniqueConstraint("source", "cache_key", name="uq_api_response_cache_key"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(max_length=32)
    cache_key: str = Field(max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    fetched_at: datetime = Field(default_factory=utcnow)


class AnalyticsSnapshot(TimestampedModel, table=True):
    """Cached analytics payload, one row per (user, kind, playlist, scope).

    Analytics are pure functions of the local database, so results live here
    until a sync or enrichment pass changes the inputs — those passes delete
    the user's rows, and the next read recomputes. playlist_id is null for
    library-scoped kinds (graph, track_map, temporal, library_stats).
    owned_only records which playlist scope the payload was computed over:
    the account's own playlists, or those plus followed ones.
    """

    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "playlist_id", "owned_only", name="uq_analytics_snapshots_scope"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    kind: SnapshotKind = Field(sa_column=enum_column(SnapshotKind, nullable=False))
    playlist_id: int | None = Field(default=None, foreign_key="playlists.id")
    owned_only: bool = Field(default=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    computed_at: datetime = Field(default_factory=utcnow)


class DiscoveryCandidate(TimestampedModel, table=True):
    """A track proposed for one playlist by the discovery pipeline.

    Candidates arrive as (title, artist) pairs or Spotify-linked
    recommendations, get resolved to Spotify tracks, and are then ranked into
    the playlist's suggestion queue. Rejected candidates stay on file so the
    same track is never proposed again.
    """

    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "playlist_id", "dedup_key", name="uq_discovery_candidates_identity"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    playlist_id: int = Field(foreign_key="playlists.id", index=True)
    source: CandidateSource = Field(sa_column=enum_column(CandidateSource, nullable=False))
    status: CandidateStatus = Field(
        default=CandidateStatus.pending,
        sa_column=enum_column(CandidateStatus, nullable=False),
    )
    title: str = Field(max_length=512)
    artist: str = Field(max_length=512)
    # Case-folded "artist|title" — one proposal per track per playlist.
    dedup_key: str = Field(max_length=255)
    # The library artist whose similarity/seed produced this candidate.
    seed_artist: str | None = Field(default=None, max_length=512)
    spotify_id: str | None = Field(default=None, max_length=64)
    isrc: str | None = Field(default=None, max_length=16)
    album_name: str | None = Field(default=None, max_length=512)
    duration_ms: int | None = Field(default=None)
    # Deezer 30-second preview, resolved after the Spotify match.
    preview_url: str | None = Field(default=None, sa_column=Column(Text))
    # Raw audio features (ReccoBeats), fetched post-resolution; percentile
    # ranking happens at read time against the current library space.
    features: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class SuggestionFeedback(TimestampedModel, table=True):
    """One review decision on a candidate — the ranker's training signal.

    The artist is denormalized so per-artist accept/reject tallies (which
    re-weight future rankings) are one aggregate query.
    """

    __tablename__ = "suggestion_feedback"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    candidate_id: int = Field(foreign_key="discovery_candidates.id", index=True)
    playlist_id: int = Field(foreign_key="playlists.id", index=True)
    artist: str = Field(index=True, max_length=512)
    action: FeedbackAction = Field(sa_column=enum_column(FeedbackAction, nullable=False))


class SavedTrack(TimestampedModel, table=True):
    """One track in the user's Liked Songs library.

    A removal flips is_removed instead of deleting the row, so the library's
    add/remove history survives; a re-save reactivates the same row with a
    fresh saved_at. This row-level trail is the saved-library counterpart of
    SyncEvent (which is playlist-scoped).
    """

    __tablename__ = "saved_tracks"
    __table_args__ = (UniqueConstraint("user_id", "track_id", name="uq_saved_tracks_user_track"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    track_id: int = Field(foreign_key="tracks.id", index=True)
    saved_at: datetime | None = Field(default=None)
    is_removed: bool = Field(default=False)
    removed_at: datetime | None = Field(default=None)


class PlayEvent(TimestampedModel, table=True):
    """One play from the recently-played history.

    Spotify timestamps each play uniquely per user, so (user_id, played_at)
    dedupes overlapping capture windows on replay.
    """

    __tablename__ = "play_events"
    __table_args__ = (
        UniqueConstraint("user_id", "played_at", name="uq_play_events_user_played_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    track_id: int = Field(foreign_key="tracks.id", index=True)
    played_at: datetime = Field()
    # Where the play happened, when Spotify reports it: context type
    # (playlist/album/artist/show) and the context's URI.
    context_type: str | None = Field(default=None, max_length=32)
    context_uri: str | None = Field(default=None, max_length=128)


class TopItemsSnapshot(TimestampedModel, table=True):
    """A point-in-time ranking of the user's top artists or tracks.

    One capture pass writes six rows (artist/track x short/medium/long),
    all sharing captured_at. items is the ranked list as JSON — snapshots
    are immutable history, never updated in place.
    """

    __tablename__ = "top_items_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    kind: TopItemKind = Field(sa_column=enum_column(TopItemKind, nullable=False))
    time_range: TopTimeRange = Field(sa_column=enum_column(TopTimeRange, nullable=False))
    captured_at: datetime = Field(default_factory=utcnow, index=True)
    # Ranked [{"rank": 1, "spotify_id": ..., "name": ..., ...}] — track items
    # also carry their artist names.
    items: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )


class Digest(TimestampedModel, table=True):
    """One weekly digest — a curated summary of what changed and what's queued.

    Keyed by the Monday the covered week starts on; regenerating a week
    rebuilds the same row's items. read_at drives the inbox unread marker.
    """

    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_digests_user_week"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    # Monday 00:00 UTC of the week the digest covers.
    week_start: datetime = Field()
    generated_at: datetime = Field(default_factory=utcnow)
    read_at: datetime | None = Field(default=None)
    # Rollup counts plus the week's frontier reading — the next digest diffs
    # against it to report frontier movement.
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class DigestItem(TimestampedModel, table=True):
    """One entry in a digest section, carrying its deep-link targets."""

    __tablename__ = "digest_items"
    __table_args__ = (UniqueConstraint("digest_id", "position", name="uq_digest_items_position"),)

    id: int | None = Field(default=None, primary_key=True)
    digest_id: int = Field(foreign_key="digests.id", index=True)
    position: int = Field()
    section: DigestSection = Field(sa_column=enum_column(DigestSection, nullable=False))
    title: str = Field(max_length=512)
    body: str | None = Field(default=None, sa_column=Column(Text))
    # Deep-link targets: whichever apply to the item.
    playlist_id: int | None = Field(default=None, foreign_key="playlists.id")
    candidate_id: int | None = Field(default=None, foreign_key="discovery_candidates.id")
    genre: str | None = Field(default=None, max_length=256)
    # Section-specific readouts (counts, fit scores) for the inbox rendering.
    extra: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class RadioSession(TimestampedModel, table=True):
    """One generated radio session: an ordered ~25-track listening run."""

    __tablename__ = "radio_sessions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    seed_kind: RadioSeedKind = Field(sa_column=enum_column(RadioSeedKind, nullable=False))
    seed_playlist_id: int | None = Field(default=None, foreign_key="playlists.id")
    seed_genre: str | None = Field(default=None, max_length=256)
    # Track ids given as an explicit seed set, when seeded from tracks.
    seed_track_ids: list[int] | None = Field(default=None, sa_column=Column(JSON))
    # Human-readable seed description, e.g. "GYM" or "trip hop".
    label: str = Field(max_length=512)
    # Fraction of the session drawn from discovery candidates.
    discovery_ratio: float = Field(default=0.2)


class RadioItem(TimestampedModel, table=True):
    """One positioned entry in a radio session.

    Title/artist/preview are denormalized at build time so the session plays
    back exactly as generated, whatever happens to the underlying rows.
    """

    __tablename__ = "radio_items"
    __table_args__ = (UniqueConstraint("session_id", "position", name="uq_radio_items_position"),)

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="radio_sessions.id", index=True)
    position: int = Field()
    kind: RadioItemKind = Field(sa_column=enum_column(RadioItemKind, nullable=False))
    track_id: int | None = Field(default=None, foreign_key="tracks.id")
    candidate_id: int | None = Field(default=None, foreign_key="discovery_candidates.id")
    title: str = Field(max_length=512)
    artist: str = Field(max_length=512)
    spotify_id: str | None = Field(default=None, max_length=64)
    preview_url: str | None = Field(default=None, sa_column=Column(Text))
    # Transition readouts for the tracklist: BPM and Camelot wheel position.
    tempo: float | None = Field(default=None)
    camelot: str | None = Field(default=None, max_length=4)
    feedback: RadioItemFeedback | None = Field(
        default=None, sa_column=enum_column(RadioItemFeedback, nullable=True)
    )
    # Set when a kept candidate was added to a playlist (undo target).
    journal_id: int | None = Field(default=None, foreign_key="mutation_journal.id")


class InsightEdition(TimestampedModel, table=True):
    """One frozen weekly reading of the insights survey — the field journal.

    Each edition snapshots the headline metrics at compile time and the
    generated narrative lines (diffs vs the previous edition). Keyed by the
    Monday the week starts on and the playlist scope, so recompiling a week
    rebuilds the same row. edition_number is the human-facing sequence
    (edition 1 = baseline reading, no deltas).
    """

    __tablename__ = "insight_editions"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", "owned_only", name="uq_insight_editions_week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    # Monday 00:00 UTC of the week the edition covers.
    week_start: datetime = Field()
    edition_number: int = Field()
    owned_only: bool = Field(default=True)
    generated_at: datetime = Field(default_factory=utcnow)
    # Headline metric readings frozen at compile time (the delta source for the
    # next edition): entropy, effective genres, GS-score, fingerprint, etc.
    headline: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # Generated field-manual lines describing what moved since last edition.
    narrative: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )


class MutationJournal(TimestampedModel, table=True):
    """Undo log: inverse payload restores the state the operation replaced."""

    __tablename__ = "mutation_journal"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    op_type: MutationOpType = Field(sa_column=enum_column(MutationOpType, nullable=False))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    inverse_payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: MutationStatus = Field(
        default=MutationStatus.pending,
        sa_column=enum_column(MutationStatus, nullable=False),
    )
    undone_at: datetime | None = Field(default=None)


class OpPreview(TimestampedModel, table=True):
    """A persisted bulk-algebra dry run.

    Apply consumes the stored delta manifest exactly as previewed — nothing is
    recomputed. The fingerprint captures the library state the manifest was
    computed against; apply refuses (409) when the library has moved since.
    """

    __tablename__ = "op_previews"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    operation: BulkOperation = Field(sa_column=enum_column(BulkOperation, nullable=False))
    # The expression as requested: source playlist ids, target, new-name.
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # Computed delta: per-playlist adds/removes, exactly what apply performs.
    manifest: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # sha256 over the library's playlist membership at preview time.
    fingerprint: str = Field(max_length=64)
