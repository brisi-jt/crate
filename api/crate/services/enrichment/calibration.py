"""Library-percentile calibration for audio features.

ReccoBeats/FreqBlog values come from Essentia models whose distributions
differ sharply from Spotify's (acousticness saturates near 0.98, speechiness
shifts ~10x). Analytics therefore rank tracks against these library
percentiles, never against absolute Spotify-era thresholds.
"""

from statistics import quantiles

from sqlmodel import Session, select

from crate.model.enums import FeatureStatus
from crate.model.orm import FeatureCalibration, TrackFeatures
from crate.model.orm.base import utcnow

# Continuous features worth ranking. key and mode are categorical and stay out.
CALIBRATED_FEATURES = (
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "liveness",
    "speechiness",
    "tempo",
    "loudness",
)


def percentile_anchors(values: list[float]) -> tuple[float, float, float]:
    """(p10, p50, p90) with linear interpolation; a lone value pins all three."""
    if len(values) == 1:
        return values[0], values[0], values[0]
    cuts = quantiles(values, n=10, method="inclusive")
    return cuts[0], cuts[4], cuts[8]


def recompute_calibration(session: Session) -> None:
    """Refresh every feature's percentile row from current present features."""
    rows = session.exec(
        select(TrackFeatures).where(TrackFeatures.status == FeatureStatus.present)
    ).all()
    for feature in CALIBRATED_FEATURES:
        values = [v for row in rows if (v := getattr(row, feature)) is not None]
        if not values:
            continue
        p10, p50, p90 = percentile_anchors(sorted(values))
        calibration = session.exec(
            select(FeatureCalibration).where(FeatureCalibration.feature == feature)
        ).first()
        if calibration is None:
            calibration = FeatureCalibration(
                feature=feature, p10=p10, p50=p50, p90=p90, sample_size=len(values)
            )
        else:
            calibration.p10 = p10
            calibration.p50 = p50
            calibration.p90 = p90
            calibration.sample_size = len(values)
            calibration.computed_at = utcnow()
        session.add(calibration)
    session.commit()
