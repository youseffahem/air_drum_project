"""TEST-FEATURE-1: analytic derivation, masking, geometry, and observation alignment."""

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from spacedrums.contracts import HandObservation, StickObservation
from spacedrums.contracts import schema as contracts
from spacedrums.features.core import FeatureCore, closest_surface_point
from spacedrums.features.groups import GROUPS, group_indices
from spacedrums.features.schema import FeatureSchema
from spacedrums.geometry.zones import Arc, Segment


def test_descriptor_dimension_and_contract(schema, track_factory):
    assert schema.dimension == 36 + 5 * len(schema.zones)
    assert len(set(schema.names)) == schema.dimension
    assert sum(schema.descriptor()["group_dimensions"].values()) == schema.dimension
    row = FeatureCore(schema).update(track_factory(0))
    contracts.validate("kinematic-features", row.to_dict())
    assert len(group_indices(schema, ["POS"])) == 2 + 2 * len(schema.zones)
    assert all(f["unit"] and f["derivation"] and f["mask_rule"] for f in schema.fields)


def test_analytic_filter_values_and_stationary_direction(schema, track_factory):
    core = FeatureCore(schema)
    r = core.update(track_factory(0, tip_velocity=(3.0, 4.0), tip_acceleration=(1.0, 2.0)))
    v = dict(zip(schema.names, r.values, strict=True))
    assert v["speed"] == 5
    assert v["direction_x"] == 0.6 and v["direction_y"] == 0.8
    assert v["vertical_velocity"] == v["vy"] == 4
    assert v["acc_tangent"] == pytest.approx(2.2)
    assert v["acc_normal"] == pytest.approx(0.4)
    r = core.update(track_factory(1, tip_velocity=(0.0, 0.0)))
    for n in ("direction_x", "direction_y", "acc_normal", "acc_tangent"):
        assert not r.mask[schema.index[n]] and r.values[schema.index[n]] == 0


def test_actual_dt_fallback_acceleration_and_wrapped_angle(schema, track_factory):
    core = FeatureCore(schema)
    core.update(
        track_factory(
            0, t_capture=100.0, tip_velocity=(0.0, 0.0), tip_acceleration=None, axis_angle=math.pi - 0.01
        )
    )
    r = core.update(
        track_factory(
            5, t_capture=100.2, tip_velocity=(0.4, -0.2), tip_acceleration=None, axis_angle=-math.pi + 0.01
        )
    )
    assert r.dt == pytest.approx(0.2)
    assert r.values[schema.index["ax"]] == pytest.approx(2)
    assert r.values[schema.index["ay"]] == pytest.approx(-1)
    assert r.values[schema.index["axis_omega"]] == pytest.approx(0.1)
    # Frame-id gaps do not impersonate the capture queue's drop count.
    assert not r.mask[schema.index["dropped_since_last"]]


@pytest.mark.parametrize("bad", ["INVALID", "STALE"])
def test_full_mask_and_reset_after_gap(schema, track_factory, bad):
    core = FeatureCore(schema)
    core.update(track_factory(0))
    gap = core.update(track_factory(1, status=bad))
    assert not any(gap.mask) and not any(gap.values)
    r = core.update(track_factory(2, tip_acceleration=None))
    assert not r.mask[schema.index["ax"]]
    assert not r.mask[schema.index["axis_omega"]]
    assert r.dt == pytest.approx(0.03)


def test_degraded_reset_and_per_hand_state(schema, track_factory):
    core = FeatureCore(schema)
    core.update(track_factory(0, hand="LEFT"))
    right = core.update(track_factory(0, status="DEGRADED"))
    assert right.values[schema.index["degraded"]] == 1 and right.dt == 0
    reset = core.update(track_factory(1, reset_reason="MANUAL", tip_acceleration=None))
    assert not reset.mask[schema.index["ax"]]
    core.reset("RIGHT")
    assert core.update(track_factory(0)).dt == 0


@pytest.mark.parametrize("i,t", [(0, 100.03), (1, 100.0), (1, float("nan"))])
def test_nonmonotonic_time_or_frame_refused(schema, track_factory, i, t):
    core = FeatureCore(schema)
    core.update(track_factory(0))
    with pytest.raises(ValueError):
        core.update(track_factory(i, t_capture=t))


def test_same_frame_hand_stick_and_missing_masks(schema, track_factory):
    t = track_factory(0)
    points = tuple((0.3 + i * 0.01, 0.4) for i in range(21))
    hand = HandObservation(0, 100.0, "RIGHT", True, "synthetic", points, None, 0.9, (0.3, 0.4, 0.2, 0.1))
    stick = StickObservation(
        0, 100.0, "RIGHT", True, "GEOM", (0.3, 0.4), (0.0, 1.0), (0.4, 0.4), 0.8, 0.7, 0.2
    )
    r = FeatureCore(schema).update(t, hand=hand, stick=stick)
    assert r.values[schema.index["landmark_9_x"]] == pytest.approx(1)
    assert r.values[schema.index["axis_confidence"]] == 0.7
    assert r.values[schema.index["stick_length"]] == 0.2
    assert r.values[schema.index["bbox_width"]] == 0.2
    with pytest.raises(ValueError, match="same frame"):
        FeatureCore(schema).update(t, hand=replace(hand, frame_id=1))
    invisible = replace(hand, landmark_visibility=tuple([0.0] * 21))
    r = FeatureCore(schema).update(t, hand=invisible)
    assert not r.mask[schema.index["landmark_9_x"]]
    collapsed = replace(hand, landmarks=tuple([(0.3, 0.4)] * 21))
    r = FeatureCore(schema).update(t, hand=collapsed)
    assert not r.mask[schema.index["landmark_9_x"]]


def test_surface_projection_endpoints_eccentric_rotated_arcs():
    assert np.allclose(closest_surface_point(Segment((0.0, 0.0), (1.0, 0.0)), (2.0, 3.0)), (1.0, 0.0))
    arc = Arc((0.2, 0.4), 0.5, 0.1, 0.4, math.pi, math.tau)
    for p in ((0.2, 0.0), (1.0, 0.5), (-0.2, 0.8), (0.2, 0.4)):
        result = closest_surface_point(arc, p)
        dense = np.array([arc.point_at(t) for t in np.linspace(math.pi, math.tau, 10001)])
        assert np.linalg.norm(result - p) <= np.linalg.norm(dense - p, axis=1).min() + 1e-8


def test_zone_signed_distance_relative_position_tts(schema, track_factory):
    r = FeatureCore(schema).update(track_factory(0, tip_filtered=(0.4, 0.5), tip_velocity=(0.0, 1.0)))
    assert r.values[schema.index["distance_snare"]] == pytest.approx(0.08, abs=1e-7)
    assert r.values[schema.index["relative_snare_y"]] == pytest.approx(-0.08)
    assert r.values[schema.index["tts_snare"]] == pytest.approx(0.08, abs=1e-7)
    r = FeatureCore(schema).update(track_factory(0, tip_filtered=(0.4, 0.5), tip_velocity=(0.0, -1.0)))
    assert r.values[schema.index["tts_snare"]] == schema.tts_clip_s


def test_jerk_fallback_is_bounded_and_default_off(schema, track_factory):
    assert "jx" not in schema.names
    s = FeatureSchema(schema.zones_config, groups=GROUPS)
    core = FeatureCore(s)
    for i, v in enumerate((0.0, 0.03, 0.12)):
        r = core.update(track_factory(i, tip_velocity=(v, 0.0), tip_acceleration=None))
    assert r.values[s.index["jx"]] == pytest.approx(66.6666666667)


def test_descriptor_file_matches_code(schema):
    descriptor = json.loads(Path("schemas/feature-schema-v1.json").read_text())
    assert descriptor == schema.descriptor()


@pytest.mark.parametrize("groups", [("WHAT",), ()])
def test_bad_groups(schema, groups):
    with pytest.raises(ValueError):
        FeatureSchema(schema.zones_config, groups=groups)
