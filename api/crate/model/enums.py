"""Enumerations for every persisted status/source/type field.

Stored as plain VARCHAR (non-native enums), so adding a member never requires
a migration.
"""

from enum import StrEnum


class CredentialStatus(StrEnum):
    """Health of a stored Spotify credential."""

    active = "active"
    # Refresh was rejected by Spotify — the user must re-consent via
    # /v1/auth/spotify/connect before syncing can resume.
    needs_reauth = "needs_reauth"


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


class MutationOpType(StrEnum):
    """Reversible write operations recorded in the mutation journal."""

    add_tracks = "add_tracks"
    remove_tracks = "remove_tracks"
    create_playlist = "create_playlist"
    rename_playlist = "rename_playlist"
    reorder = "reorder"


class MutationStatus(StrEnum):
    """Lifecycle of a journaled mutation."""

    pending = "pending"
    applied = "applied"
    undone = "undone"
