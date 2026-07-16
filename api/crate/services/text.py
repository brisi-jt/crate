"""Text normalization applied to externally-sourced names at ingest.

Spotify (and any upstream) can hand back names carrying raw control characters
or lone UTF-16 surrogates. Stored verbatim, they later leak into API responses
and break strict JSON consumers (``jq``: "Invalid control character at"). The
serializer escapes them, but a corrupted byte still round-trips — so we scrub at
the write path, where the value enters the catalog, and keep a response-level
guard as defence in depth.
"""

import re

# C0/C1 control characters (U+0000 to U+001F, U+007F to U+009F). Names never
# legitimately carry these; tabs/newlines in a name are noise, so they go too.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# Lone UTF-16 surrogate code points, which are not valid in well-formed text and
# make some JSON encoders emit invalid output.
_LONE_SURROGATES = re.compile(r"[\ud800-\udfff]")


def clean_name(value: str) -> str:
    """Strip control characters and lone surrogates from a name.

    Idempotent: cleaning an already-clean value is a no-op, so it is safe to run
    at every write and in a backfill.
    """
    return _LONE_SURROGATES.sub("", _CONTROL_CHARS.sub("", value))


def clean_optional_name(value: str | None) -> str | None:
    return clean_name(value) if value is not None else None
