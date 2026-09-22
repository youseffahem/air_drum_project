"""SYNTHETIC unit records only; no participant recordings."""

import pytest

from spacedrums.config import load_config
from spacedrums.contracts import TrackState
from spacedrums.features.schema import FeatureSchema


@pytest.fixture
def schema():
    cfg = load_config("configs/prototype.candidate.yaml")
    return FeatureSchema(cfg["zones"])


@pytest.fixture
def track_factory():
    def make(i, *, hand="RIGHT", status="VALID", **kwargs):
        live = status in ("VALID", "DEGRADED")
        values = dict(
            frame_id=i,
            t_capture=100.0 + i * 0.03,
            hand_id=hand,
            status=status,
            tracker_id="synthetic-unit",
            tip_method="GEOM",
            tip_filtered=(0.4, 0.4 + 0.003 * i) if live else None,
            tip_velocity=(0.1, 0.2 + 0.01 * i) if live else None,
            tip_acceleration=(0.2, 0.3) if live else None,
            axis_angle=0.01 * i if live else None,
            axis_angular_velocity=None,
            confidence=0.8,
            frames_since_valid=0 if status == "VALID" else 1,
            last_valid_t=100.0 if live else None,
            history_ref=None,
            reset_reason=None,
        )
        values.update(kwargs)
        return TrackState(**values)

    return make
