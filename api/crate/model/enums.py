"""Enumerations for every persisted status/source/type field.

Stored as plain VARCHAR (non-native enums), so adding a member never requires
a migration.
"""

from enum import StrEnum


class ReauthReason(StrEnum):
    """Why a Spotify credential needs re-consent."""

    # The refresh token hit Spotify's 6-month authorization lifetime (the
    # token endpoint answered 400 invalid_grant).
    token_expired = "token_expired"
    # Spotify rejected the refresh for any other reason.
    refresh_rejected = "refresh_rejected"


class CredentialStatus(StrEnum):
    """Health of a stored Spotify credential."""

    active = "active"
    # Refresh was rejected by Spotify — the user must re-consent via
    # /v1/auth/spotify/connect before syncing can resume.
    needs_reauth = "needs_reauth"
    # The refresh token aged out of Spotify's 6-month authorization lifetime;
    # re-consent is the only recovery (refreshing must not be retried).
    needs_reauth_expired = "needs_reauth_expired"

    @property
    def requires_reauth(self) -> bool:
        return self in (CredentialStatus.needs_reauth, CredentialStatus.needs_reauth_expired)

    @property
    def reauth_reason(self) -> ReauthReason | None:
        if self is CredentialStatus.needs_reauth_expired:
            return ReauthReason.token_expired
        if self is CredentialStatus.needs_reauth:
            return ReauthReason.refresh_rejected
        return None

    @classmethod
    def for_reauth_reason(cls, reason: ReauthReason) -> "CredentialStatus":
        if reason is ReauthReason.token_expired:
            return cls.needs_reauth_expired
        return cls.needs_reauth


class PlaylistSyncStatus(StrEnum):
    """Where a playlist sits in the sync lifecycle."""

    pending = "pending"
    synced = "synced"
    error = "error"


class SyncEventType(StrEnum):
    """What changed, as observed by a sync pass or performed by crate itself."""

    added = "added"
    removed = "removed"
    reordered = "reordered"
    playlist_created = "playlist_created"
    playlist_renamed = "playlist_renamed"
    playlist_deleted = "playlist_deleted"


class SyncEventSource(StrEnum):
    """Who caused an event: observed on Spotify (sync) or written by crate."""

    sync = "sync"
    crate = "crate"


class FeatureSource(StrEnum):
    """Which provider supplied a track's audio features."""

    reccobeats = "reccobeats"
    freqblog = "freqblog"
    # Self-hosted Essentia extraction (Hybrid-B) — not wired up yet; rows
    # marked missing are its future work queue.
    essentia = "essentia"


class FeatureStatus(StrEnum):
    """Whether a track's feature lookup produced values."""

    present = "present"
    # Every available source missed — the track waits for Essentia analysis.
    missing = "missing"


class SimilaritySource(StrEnum):
    """Which service asserted an artist-similarity edge."""

    lastfm = "lastfm"
    listenbrainz = "listenbrainz"


class TagSource(StrEnum):
    """Where an artist tag came from."""

    lastfm = "lastfm"
    enao = "enao"


class SnapshotKind(StrEnum):
    """Which analytics payload an AnalyticsSnapshot row caches."""

    graph = "graph"
    track_map = "track_map"
    temporal = "temporal"
    library_stats = "library_stats"
    playlist_analytics = "playlist_analytics"
    flow = "flow"
    artist_galaxy = "artist_galaxy"
    frontier = "frontier"
    insights = "insights"
    insight_pins = "insight_pins"
    # Cluster proposal for the current triage queue — keyed by source and
    # filter, invalidated when the queue's content hash changes. Rides the same
    # 202 + background-compute path as track_map so UMAP/HDBSCAN never runs in
    # the request path.
    triage_cluster = "triage_cluster"


class MutationOpType(StrEnum):
    """Reversible write operations recorded in the mutation journal."""

    add_tracks = "add_tracks"
    remove_tracks = "remove_tracks"
    create_playlist = "create_playlist"
    rename_playlist = "rename_playlist"
    reorder = "reorder"
    # One bulk-algebra apply: a previewed delta across one or more playlists.
    bulk = "bulk"
    # Remove tracks from the Liked Songs library (DELETE /me/tracks). Inverse
    # re-saves them (PUT /me/tracks).
    unsave_track = "unsave_track"
    # One triage filing: add a track to N playlists (optionally creating and
    # seeding a new one) and optionally unsave it — one journal entry with one
    # composite inverse, so the whole filing is one-click undoable.
    file_track = "file_track"


class MutationStatus(StrEnum):
    """Lifecycle of a journaled mutation."""

    pending = "pending"
    applied = "applied"
    undone = "undone"
    # A bulk apply where some playlists succeeded and some failed — the
    # journal keeps per-playlist results, and undo restores what did apply.
    partial = "partial"


class BulkOperation(StrEnum):
    """Set expressions the bulk-algebra preview can compute."""

    union = "union"
    difference = "difference"
    intersect = "intersect"
    dedupe = "dedupe"
    sync_subset_to_parent = "sync_subset_to_parent"


class CandidateSource(StrEnum):
    """Which pipeline proposed a discovery candidate."""

    # Similar artists of the playlist's top artists, then their top tracks.
    lastfm = "lastfm"
    # Track recommendations seeded by the playlist's exemplar tracks.
    reccobeats = "reccobeats"
    # Exemplar artists of an ENAO frontier genre, then their top tracks.
    enao = "enao"


class CandidateStatus(StrEnum):
    """Lifecycle of a discovery candidate."""

    # Proposed, not yet matched to a Spotify track.
    pending = "pending"
    # Matched to a Spotify track — eligible for the suggestion queue.
    resolved = "resolved"
    # Spotify search found no match; kept so it is never re-proposed.
    unresolvable = "unresolvable"
    # Reviewed and added to the playlist.
    accepted = "accepted"
    # Reviewed and declined; excluded from every future generation pass.
    rejected = "rejected"


class FeedbackAction(StrEnum):
    """A review decision on a suggested track."""

    accept = "accept"
    reject = "reject"
    skip = "skip"


class DigestSection(StrEnum):
    """Which part of a weekly digest an item belongs to."""

    # New suggestion counts, per playlist.
    suggestions = "suggestions"
    # Top-ranked candidates nobody has reviewed yet.
    candidates = "candidates"
    # Library changes observed by sync passes.
    library = "library"
    # Listening notes from the play history.
    listening = "listening"
    # Movement on the genre frontier.
    frontier = "frontier"


class RadioSeedKind(StrEnum):
    """What a radio session was seeded from."""

    playlist = "playlist"
    tracks = "tracks"
    genre = "genre"


class RadioItemKind(StrEnum):
    """Where a radio item came from."""

    # A track already in the library.
    library = "library"
    # A discovery candidate interleaved for audition.
    discovery = "discovery"


class RadioItemFeedback(StrEnum):
    """The listener's verdict on one radio item."""

    kept = "kept"
    skipped = "skipped"


class TopItemKind(StrEnum):
    """What a top-items snapshot ranks."""

    artist = "artist"
    track = "track"


class TopTimeRange(StrEnum):
    """Spotify affinity window a top-items snapshot covers.

    Maps to the API's short_term (~4 weeks), medium_term (~6 months) and
    long_term (~1 year) ranges.
    """

    short = "short"
    medium = "medium"
    long = "long"


class EvidenceKind(StrEnum):
    """A named triage-suggestion signal.

    Each destination suggestion carries one evidence row per kind, separately
    labeled — never a single blended score. sonic_fit is proximity to the
    playlist's centroid in percentile space; artist_overlap counts the track's
    artists already present; placement_history looks at where feature-space
    neighbours were filed; vibe_match overlaps the playlist name/description
    tokens against the track's genre tokens.
    """

    sonic_fit = "sonic_fit"
    artist_overlap = "artist_overlap"
    placement_history = "placement_history"
    vibe_match = "vibe_match"
