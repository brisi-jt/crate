"""Credential re-auth state mapped to RFC 7807 conflicts.

Shared by the sync runner and the mutations wiring so both surface the same
problem codes: SPOTIFY_SESSION_EXPIRED when the refresh token aged out of
Spotify's 6-month authorization lifetime, SPOTIFY_REAUTH_REQUIRED for any
other rejection.
"""

from crate.errors import AppError
from crate.model.enums import CredentialStatus


def reauth_conflict(status: CredentialStatus) -> AppError:
    if status == CredentialStatus.needs_reauth_expired:
        return AppError(
            409,
            "Spotify session expired",
            detail=(
                "Spotify authorizations last 6 months; this one has lapsed. "
                "Reconnect via /v1/auth/spotify/connect to sign in again."
            ),
            error_code="SPOTIFY_SESSION_EXPIRED",
        )
    return AppError(
        409,
        "Spotify authorization expired",
        detail="Reconnect via /v1/auth/spotify/connect to restore access.",
        error_code="SPOTIFY_REAUTH_REQUIRED",
    )
