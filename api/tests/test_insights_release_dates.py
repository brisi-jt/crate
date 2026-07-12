"""Release-year parsing across Spotify's three precisions."""

from crate.services.insights.release_dates import parse_release_year


def test_parses_day_precision() -> None:
    assert parse_release_year("1998-06-30") == 1998


def test_parses_month_precision() -> None:
    assert parse_release_year("1998-06") == 1998


def test_parses_year_precision() -> None:
    assert parse_release_year("1998") == 1998


def test_none_and_empty_are_none() -> None:
    assert parse_release_year(None) is None
    assert parse_release_year("") is None


def test_implausible_leading_year_is_none() -> None:
    assert parse_release_year("abc-01-01") is None
    assert parse_release_year("99-01-01") is None
