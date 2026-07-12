"""Insight pins — determinism and per-surface content."""

import pytest

from crate.services.insights import pins

pytestmark = pytest.mark.unit


def _payload(**over: object) -> dict:
    base: dict = {
        "taste_identity": {
            "fingerprint": [
                {"feature": "energy", "percentile": 0.9},
                {"feature": "valence", "percentile": 0.5},
                {"feature": "danceability", "percentile": 0.5},
                {"feature": "acousticness", "percentile": 0.1},
                {"feature": "instrumentalness", "percentile": 0.5},
                {"feature": "liveness", "percentile": 0.5},
                {"feature": "speechiness", "percentile": 0.5},
                {"feature": "tempo", "percentile": 0.5},
                {"feature": "loudness", "percentile": 0.5},
            ],
            "genre_rarity": {
                "mean_rarity": 0.5,
                "rarest": [
                    {"genre": "catstep", "enao_rank": 1496, "rarity": 1.0},
                    {"genre": "vapor", "enao_rank": 1000, "rarity": 0.67},
                ],
            },
        },
        "sonic_signatures": {
            "mood": {
                "shares": {
                    "happy_energetic": 0.4,
                    "energetic_tense": 0.3,
                    "peaceful_content": 0.2,
                    "calm_sad": 0.1,
                },
                "total": 100,
            }
        },
        "archaeology": {
            "abandoned_playlists": [
                {"playlist_id": 7, "name": "Old Mixes", "months_dormant": 18},
                {"playlist_id": 3, "name": "Dusty", "months_dormant": 8},
            ]
        },
    }
    base.update(over)
    return base


def _galaxy() -> dict:
    return {
        "nodes": [
            {"id": "aphex twin", "name": "Aphex Twin", "track_count": 15, "playlist_count": 5},
            {
                "id": "boards of canada",
                "name": "Boards of Canada",
                "track_count": 8,
                "playlist_count": 3,
            },
            {"id": "solo", "name": "Solo", "track_count": 1, "playlist_count": 1},
        ]
    }


def test_field_pins_include_extreme_axes() -> None:
    result = pins.compute_pins_payload(_payload(), _galaxy(), "field")
    assert result["surface"] == "field"
    anchors = {pin["anchor"] for pin in result["pins"]}
    # energy P90 and acousticness P10 are extreme; valence P50 is not.
    assert "energy" in anchors
    assert "acousticness" in anchors
    assert "valence" not in anchors


def test_field_pins_capped_and_deterministic() -> None:
    a = pins.compute_pins_payload(_payload(), _galaxy(), "field")["pins"]
    b = pins.compute_pins_payload(_payload(), _galaxy(), "field")["pins"]
    assert a == b
    assert len(a) <= pins.MAX_PINS


def test_galaxy_pins_bridges_and_catalogs() -> None:
    result = pins.compute_pins_payload(_payload(), _galaxy(), "galaxy")
    ids = [pin["dismissible_id"] for pin in result["pins"]]
    # Aphex Twin is both the top bridge and the deepest catalog.
    assert any("aphex twin:playlist_count" in did for did in ids)
    assert any("aphex twin:track_count" in did for did in ids)
    # the 1-track/1-playlist "solo" node clears no threshold.
    assert not any("solo" in did for did in ids)


def test_graph_pins_dormancy_and_rarity() -> None:
    result = pins.compute_pins_payload(_payload(), _galaxy(), "graph")
    refs = {pin["metric_ref"] for pin in result["pins"]}
    assert "dormancy" in refs
    assert "rarity" in refs
    # dismissible ids are stable
    assert all(pin["dismissible_id"].startswith("graph:") for pin in result["pins"])


def test_dismissible_id_is_stable_shape() -> None:
    result = pins.compute_pins_payload(_payload(), _galaxy(), "field")
    for pin in result["pins"]:
        assert pin["dismissible_id"] == f"field:{pin['anchor']}:{pin['metric_ref']}"
