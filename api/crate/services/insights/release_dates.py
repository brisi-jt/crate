"""Parse Spotify album release dates into a comparable year.

Spotify reports release_date at one of three precisions — "year" ("1998"),
"month" ("1998-06"), or "day" ("1998-06-30"). The leading four digits are the
release year in every case, which is all the decade / era / taste-freeze
analytics need.
"""


def parse_release_year(release_date: str | None) -> int | None:
    """Leading four-digit year from a Spotify release_date, or None.

    Accepts any of Spotify's three precisions; anything without a plausible
    four-digit leading year (1000..9999) returns None rather than a guess.
    """
    if not release_date:
        return None
    head = release_date[:4]
    if len(head) != 4 or not head.isdigit():
        return None
    year = int(head)
    if year < 1000 or year > 9999:
        return None
    return year
