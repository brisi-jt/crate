"""FreqBlog monthly-allowance accounting: consume, hard stop, month rollover."""

import pytest
from sqlmodel import Session, select

from crate.model.orm import FreqBlogBudget
from crate.services.enrichment.freqblog import try_consume_budget

pytestmark = pytest.mark.unit


def test_first_call_of_month_creates_counter_and_consumes(session: Session) -> None:
    assert try_consume_budget(session, month="2026-07", limit=1000) is True
    row = session.exec(select(FreqBlogBudget)).one()
    assert row.month == "2026-07"
    assert row.used == 1


def test_consumption_accumulates(session: Session) -> None:
    for _ in range(3):
        assert try_consume_budget(session, month="2026-07", limit=1000)
    row = session.exec(select(FreqBlogBudget)).one()
    assert row.used == 3


def test_hard_stop_at_limit(session: Session) -> None:
    for _ in range(2):
        assert try_consume_budget(session, month="2026-07", limit=2)
    assert try_consume_budget(session, month="2026-07", limit=2) is False
    row = session.exec(select(FreqBlogBudget)).one()
    assert row.used == 2  # the refused call must not count


def test_new_month_starts_a_fresh_counter(session: Session) -> None:
    for _ in range(2):
        try_consume_budget(session, month="2026-07", limit=2)
    assert try_consume_budget(session, month="2026-08", limit=2) is True
    months = {row.month: row.used for row in session.exec(select(FreqBlogBudget)).all()}
    assert months == {"2026-07": 2, "2026-08": 1}
