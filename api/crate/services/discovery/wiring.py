"""Production wiring for a discovery pass.

One run walks the requested playlists through generate -> resolve -> features
-> previews, building clients from settings. Without a Last.fm key the
similar-artist source is skipped (the pass still runs on recommendations);
with CRATE_FAKE_SPOTIFY set, resolution short-circuits to deterministic
invented IDs so local development needs no Spotify credential.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from crate.model.enums import CandidateStatus, PlaylistSyncStatus
from crate.model.orm import DiscoveryCandidate, Playlist, User
from crate.services.discovery.generation import (
    DEFAULT_CANDIDATE_LIMIT,
    generate_for_playlist,
)
from crate.services.discovery.resolution import (
    FakeSpotifyResolver,
    TrackSearch,
    fetch_candidate_features,
    resolve_candidates,
    resolve_previews,
)
from crate.services.enrichment.cache import ResponseCache
from crate.services.enrichment.deezer import DeezerClient
from crate.services.enrichment.lastfm import LastFmClient
from crate.services.enrichment.reccobeats import ReccoBeatsClient
from crate.services.mutations.wiring import spotify_client_for_user
from crate.settings import get_settings


@dataclass
class DiscoveryReport:
    """Counts from one discovery pass."""

    playlists_processed: int = 0
    generated_lastfm: int = 0
    generated_reccobeats: int = 0
    excluded: int = 0
    resolved: int = 0
    unresolvable: int = 0
    features_fetched: int = 0
    previews_resolved: int = 0
    lastfm_skipped: bool = False
    errors: list[str] = field(default_factory=list)


@asynccontextmanager
async def _resolver_for_user(session: Session, user: User) -> AsyncIterator[TrackSearch]:
    if get_settings().fake_spotify:
        yield FakeSpotifyResolver()
        return
    async with spotify_client_for_user(session, user) as client:
        yield client


async def run_discovery(
    session: Session,
    user: User,
    *,
    playlist_id: int | None = None,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> DiscoveryReport:
    """One full discovery pass over one playlist (or every synced playlist)."""
    assert user.id is not None
    settings = get_settings()
    report = DiscoveryReport(lastfm_skipped=not settings.lastfm_api_key)

    playlist_query = (
        select(Playlist)
        .where(Playlist.user_id == user.id)
        .where(Playlist.is_deleted == False)  # noqa: E712 — SQL expression
        .where(Playlist.status == PlaylistSyncStatus.synced)
        .order_by(col(Playlist.id))
    )
    if playlist_id is not None:
        playlist_query = playlist_query.where(Playlist.id == playlist_id)
    playlists = session.exec(playlist_query).all()

    async with AsyncExitStack() as stack:
        reccobeats = ReccoBeatsClient(cache=ResponseCache(session, source="reccobeats"))
        stack.push_async_callback(reccobeats.aclose)
        deezer = DeezerClient(cache=ResponseCache(session, source="deezer"))
        stack.push_async_callback(deezer.aclose)
        lastfm: LastFmClient | None = None
        if settings.lastfm_api_key:
            lastfm = LastFmClient(
                api_key=settings.lastfm_api_key,
                cache=ResponseCache(session, source="lastfm"),
            )
            stack.push_async_callback(lastfm.aclose)

        for playlist in playlists:
            # One playlist's source failure (bad seeds, upstream 5xx) never
            # takes down the whole pass — it is reported and skipped.
            try:
                generation = await generate_for_playlist(
                    session, user, playlist, lastfm=lastfm, reccobeats=reccobeats, limit=limit
                )
            except Exception as exc:  # per-playlist isolation
                report.errors.append(f"{playlist.name}: {exc}")
                continue
            report.playlists_processed += 1
            report.generated_lastfm += generation.generated_lastfm
            report.generated_reccobeats += generation.generated_reccobeats
            report.excluded += generation.excluded

        pending = session.exec(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.user_id == user.id)
            .where(DiscoveryCandidate.status == CandidateStatus.pending)
            .order_by(col(DiscoveryCandidate.id))
        ).all()
        if pending:
            async with _resolver_for_user(session, user) as resolver:
                report.resolved = await resolve_candidates(session, list(pending), resolver)
            report.unresolvable = sum(
                1 for c in pending if c.status == CandidateStatus.unresolvable
            )

        actionable = session.exec(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.user_id == user.id)
            .where(DiscoveryCandidate.status == CandidateStatus.resolved)
            .order_by(col(DiscoveryCandidate.id))
        ).all()
        # Invented fake-mode IDs mean nothing to ReccoBeats — skip them.
        real = [c for c in actionable if c.spotify_id and not c.spotify_id.startswith("fake-")]
        try:
            report.features_fetched = await fetch_candidate_features(session, real, reccobeats)
        except Exception as exc:  # enrichment is best-effort
            report.errors.append(f"features: {exc}")
        try:
            previews = await resolve_previews(session, list(actionable), deezer)
            report.previews_resolved = previews.resolved
            report.errors.extend(previews.errors)
        except Exception as exc:  # previews are best-effort
            report.errors.append(f"previews: {exc}")

    return report
