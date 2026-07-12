"""Edition narrative diffs + compile persistence."""

import pytest
from sqlmodel import Session, select

from crate.model.orm import InsightEdition, User
from crate.services.insights import editions
from tests.test_analytics_endpoints import seed_library

pytestmark = pytest.mark.unit


def _headline(**over: object) -> dict:
    base: dict = {
        "entropy_bits": 2.0,
        "effective_genres": 4.0,
        "gs_score": 0.30,
        "archetype": "explorer",
        "mean_rarity": 0.40,
        "enriched_tracks": 100,
        "dormant_playlists": 2,
        "fingerprint": {"energy": 0.5, "valence": 0.5},
    }
    base.update(over)
    return base


def test_baseline_edition_states_no_deltas() -> None:
    lines = editions.generate_narrative(_headline(), None)
    kinds = {line["kind"] for line in lines}
    assert "baseline" in kinds
    assert all(line["kind"] != "entropy" for line in lines)


def test_entropy_widening_narrative() -> None:
    prev = _headline(entropy_bits=1.0, effective_genres=2.0)
    curr = _headline(entropy_bits=2.0, effective_genres=4.0)
    lines = editions.generate_narrative(curr, prev)
    entropy_lines = [line for line in lines if line["kind"] == "entropy"]
    assert entropy_lines
    assert "widened" in entropy_lines[0]["text"]


def test_archetype_reclassification_narrative() -> None:
    prev = _headline(archetype="specialist")
    curr = _headline(archetype="omnivore")
    lines = editions.generate_narrative(curr, prev)
    assert any("specialist -> omnivore" in line["text"] for line in lines)


def test_fingerprint_drift_narrative() -> None:
    prev = _headline(fingerprint={"energy": 0.3, "valence": 0.5})
    curr = _headline(fingerprint={"energy": 0.7, "valence": 0.5})
    lines = editions.generate_narrative(curr, prev)
    drift = [line for line in lines if line["kind"] == "fingerprint"]
    assert drift
    assert "energy" in drift[0]["text"]


def test_steady_week_when_nothing_moves() -> None:
    prev = _headline()
    curr = _headline()
    lines = editions.generate_narrative(curr, prev)
    assert lines == [
        {"kind": "steady", "text": "A steady week - no reading moved past its threshold."}
    ]


def test_compile_edition_one_is_baseline(session: Session, user: User) -> None:
    seed_library(session, user)
    edition = editions.compile_edition(session, user, owned_only=True)
    assert edition.edition_number == 1
    assert any(line["kind"] == "baseline" for line in edition.narrative)
    assert edition.headline["enriched_tracks"] == 5


def test_recompile_same_week_updates_in_place(session: Session, user: User) -> None:
    seed_library(session, user)
    first = editions.compile_edition(session, user, owned_only=True)
    again = editions.compile_edition(session, user, owned_only=True)
    assert first.id == again.id
    rows = session.exec(select(InsightEdition).where(InsightEdition.user_id == user.id)).all()
    assert len(rows) == 1
