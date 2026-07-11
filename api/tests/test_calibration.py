"""Per-feature percentile calibration — the anchor for all downstream analytics."""

import pytest
from sqlmodel import Session, select

from crate.model.enums import FeatureSource, FeatureStatus
from crate.model.orm import FeatureCalibration, Track, TrackFeatures
from crate.services.enrichment.calibration import CALIBRATED_FEATURES, recompute_calibration

pytestmark = pytest.mark.unit


def add_track_with_features(session: Session, spotify_id: str, **features) -> None:
    track = Track(spotify_id=spotify_id, name=f"t-{spotify_id}", artists=[])
    session.add(track)
    session.commit()
    session.refresh(track)
    session.add(
        TrackFeatures(
            track_id=track.id,
            status=FeatureStatus.present,
            source=FeatureSource.reccobeats,
            **features,
        )
    )
    session.commit()


def test_percentiles_computed_over_library(session: Session) -> None:
    # energy 0.0 .. 1.0 in eleven even steps: p10=0.1, p50=0.5, p90=0.9
    for i in range(11):
        add_track_with_features(session, f"s{i}", energy=i / 10)

    recompute_calibration(session)

    row = session.exec(
        select(FeatureCalibration).where(FeatureCalibration.feature == "energy")
    ).one()
    assert row.p10 == pytest.approx(0.1)
    assert row.p50 == pytest.approx(0.5)
    assert row.p90 == pytest.approx(0.9)
    assert row.sample_size == 11


def test_recompute_upserts_rather_than_duplicating(session: Session) -> None:
    add_track_with_features(session, "a", energy=0.2)
    recompute_calibration(session)
    add_track_with_features(session, "b", energy=0.8)
    recompute_calibration(session)

    rows = session.exec(
        select(FeatureCalibration).where(FeatureCalibration.feature == "energy")
    ).all()
    assert len(rows) == 1
    assert rows[0].sample_size == 2


def test_missing_feature_rows_are_excluded(session: Session) -> None:
    add_track_with_features(session, "present", energy=0.5)
    track = Track(spotify_id="missing", name="missing", artists=[])
    session.add(track)
    session.commit()
    session.refresh(track)
    session.add(TrackFeatures(track_id=track.id, status=FeatureStatus.missing))
    session.commit()

    recompute_calibration(session)

    row = session.exec(
        select(FeatureCalibration).where(FeatureCalibration.feature == "energy")
    ).one()
    assert row.sample_size == 1


def test_no_data_leaves_no_calibration_rows(session: Session) -> None:
    recompute_calibration(session)
    assert session.exec(select(FeatureCalibration)).all() == []


def test_single_sample_pins_all_percentiles_to_the_value(session: Session) -> None:
    add_track_with_features(session, "only", energy=0.42)
    recompute_calibration(session)
    row = session.exec(
        select(FeatureCalibration).where(FeatureCalibration.feature == "energy")
    ).one()
    assert row.p10 == row.p50 == row.p90 == pytest.approx(0.42)


def test_all_numeric_features_are_calibrated(session: Session) -> None:
    add_track_with_features(
        session,
        "full",
        energy=0.1,
        valence=0.2,
        danceability=0.3,
        acousticness=0.4,
        instrumentalness=0.5,
        liveness=0.6,
        speechiness=0.7,
        tempo=120.0,
        loudness=-7.5,
    )
    recompute_calibration(session)
    calibrated = {row.feature for row in session.exec(select(FeatureCalibration)).all()}
    assert calibrated == set(CALIBRATED_FEATURES)
