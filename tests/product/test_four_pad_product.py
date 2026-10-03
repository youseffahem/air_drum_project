"""SYNTHETIC product regressions: behavior assertions, never live acceptance."""

from dataclasses import replace

import numpy as np
import pytest

from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.calib.reach import ReachSettings, ReachStroke, StrokeCollector, fit_reach
from spacedrums.capture import Roi
from spacedrums.config import config_hash, load_config, validate
from spacedrums.contracts import Arm, HandId, TipMethod, TrackStatus
from spacedrums.contracts.perception import BodyReference, EndpointEvidence
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.four_pad import DISPLAY_ORDER, four_pad_layout
from spacedrums.geometry.strokes import MeasuredStrokeGeometry
from spacedrums.ui.kit import render_kit

L, R = HandId.LEFT, HandId.RIGHT


@pytest.fixture
def config():
    c = load_config("configs/prototype.candidate.yaml", "configs/product.candidate.yaml").data
    c["zones"] = four_pad_layout((0.2, 0.8), (0.30, 0.65), 0.15, 0.10)
    validate(c)
    return c


def run(config, sequence):
    audio = AudioOutput(config, latency=OutputLatency.unmeasured(), device_enabled=False, clock=lambda: 100.0)
    pipeline = DecisionPipeline(
        config,
        registry=ZoneRegistry.from_config(config["zones"]),
        session_id="SYNTHETIC",
        active_arm=Arm.A,
        hardware_id="test",
        config_hash=config_hash(config),
        audio=audio,
    )
    results = []
    for s, o in sequence:
        observations = {
            h: (hand, replace(stick, method_id=TipMethod.AXIS_REFINED)) for h, (hand, stick) in o.items()
        }
        evidence = {
            h: EndpointEvidence(
                s.frame_id,
                s.t_capture,
                h,
                "MEASURED" if stick.present else "MISSING",
                "SYNTHETIC",
                stick.tip,
                stick.axis_origin,
                stick.tip_confidence,
            )
            for h, (_, stick) in observations.items()
        }
        results.append(pipeline.step(s, observations, t_now=s.t_frame_available, endpoint_evidence=evidence))
    return results, audio


def test_display_2x2_names_gaps_equal_dimensions(config):
    zones = config["zones"]
    points = [np.array(z["shape"]["points"]) for z in zones]
    centers = [p.mean(axis=0) for p in points]
    assert [z["zone_id"] for z in zones] == list(DISPLAY_ORDER)
    assert centers[0][0] > centers[1][0]  # camera x reverses in the mirror
    assert centers[0][1] == pytest.approx(centers[1][1])
    assert centers[2][0] == pytest.approx(centers[0][0])
    assert centers[2][1] > centers[0][1]
    assert all(np.allclose(np.ptp(p, axis=0), (0.15, 0.10)) for p in points)
    assert all(z["allowed_hands"] == ["LEFT", "RIGHT"] for z in zones)


@pytest.mark.parametrize("hand", [L, R])
@pytest.mark.parametrize("zone", DISPLAY_ORDER)
def test_either_hand_hits_every_zone_with_correct_audio(config, hand, zone):
    reg = ZoneRegistry.from_config(config["zones"])
    seq = build_sequence(reg, [Swing(hand, zone, 0.3)], duration_s=1.1)
    results, audio = run(config, seq.frames)
    commits = [c for r in results for c in r.commits]
    events = [e for r in results for e in r.audio]
    assert [(c.hand_id, c.zone_id) for c in commits] == [(hand, zone)]
    assert len(events) == audio.events == 1
    assert events[0].sample_id == reg[zone].sample_id


@pytest.mark.parametrize("simultaneous", [True, False])
def test_rapid_roll_and_simultaneous_independent_events(config, simultaneous):
    reg = ZoneRegistry.from_config(config["zones"])
    swings = []
    for i in range(10):
        for hand, offset, zone in ((L, 0.0, "snare"), (R, 0.0 if simultaneous else 0.0666667, "crash_ride")):
            swings.append(Swing(hand, zone, 0.3 + i * (4 / 30) + offset, t_down=1 / 30, depth=0.12))
    seq = build_sequence(reg, swings, duration_s=2)
    results, audio = run(config, seq.frames)
    commits = [c for r in results for c in r.commits]
    assert len(commits) == audio.events == 20
    assert len({c.strike_id for c in commits}) == 20
    if simultaneous:
        assert sum(len(r.commits) == 2 for r in results) == 10


def feed(engine, points, *, hand=R, start=0.0):
    out = []
    for i, point in enumerate(points):
        out.extend(
            engine.observe(
                frame_id=i,
                t_capture=start + i / 30,
                hand_id=hand,
                position=point,
                status=TrackStatus.VALID if point else TrackStatus.DEGRADED,
                t_candidate=start + i / 30,
            )
        )
    return out


@pytest.mark.parametrize(
    "points",
    [
        [(0.8, 0.7)] * 20,  # resting inside snare
        [(x, 0.68) for x in np.linspace(0.65, 0.9, 15)],  # side entry
        [(0.8, 0.645 + (0.001 if i % 2 else -0.001)) for i in range(20)],  # noise above edge
        [(0.8, 0.65 + (0.002 if i % 2 else -0.002)) for i in range(20)],  # edge chatter
        [(0.8, 0.55), None, None, (0.8, 0.70), (0.8, 0.71)],  # reacquisition without approach
        [None] * 12 + [(0.8, 0.7)] * 10,  # initially occluded, returns inside
        [(0.8, 0.72), (0.8, 0.68), (0.8, 0.6)],  # upstroke
    ],
)
def test_negative_trajectories_emit_nothing(config, points):
    engine = MeasuredStrokeGeometry(ZoneRegistry.from_config(config["zones"]), v_min=0.15)
    assert feed(engine, points) == []


@pytest.mark.parametrize("gap", [1, 2])
def test_gap_crossing_retains_measured_approach(config, gap):
    engine = MeasuredStrokeGeometry(ZoneRegistry.from_config(config["zones"]), v_min=0.15)
    result = feed(engine, [(0.8, 0.48), (0.8, 0.52), (0.8, 0.56)] + [None] * gap + [(0.8, 0.70)])
    assert len(result) == 1
    assert result[0].zone_id == "snare"


def test_long_gap_and_teleport_do_not_strike(config):
    engine = MeasuredStrokeGeometry(ZoneRegistry.from_config(config["zones"]), v_min=0.15)
    assert not feed(engine, [(0.8, 0.5), (0.8, 0.54)] + [None] * 5 + [(0.8, 0.7)])
    engine = MeasuredStrokeGeometry(ZoneRegistry.from_config(config["zones"]), v_min=0.15)
    assert not feed(engine, [(0.8, 0.05), (0.8, 0.85)])


def test_same_downstroke_cannot_hit_both_rows(config):
    engine = MeasuredStrokeGeometry(ZoneRegistry.from_config(config["zones"]), v_min=0.15)
    out = feed(engine, [(0.8, y) for y in np.linspace(0.20, 0.9, 20)])
    assert [c.zone_id for c in out] == ["crash_ride"]


def test_prefix_invariance(config):
    points = [(0.8, y) for y in (0.2, 0.25, 0.32, 0.4, 0.3, 0.22, 0.28, 0.35, 0.65)]

    def events(p):
        engine = MeasuredStrokeGeometry(ZoneRegistry.from_config(config["zones"]), v_min=0.15)
        return [(c.frame_id, c.zone_id, c.t_impact_est) for c in feed(engine, p)]

    full = events(points)
    for n in range(1, len(points)):
        assert events(points[:n]) == [c for c in full if c[0] < n]


def strokes():
    out = []
    for i, z in enumerate(DISPLAY_ORDER):
        x, bottom = (0.8, 0.2)[i % 2], (0.35, 0.70)[i // 2]
        for j in range(6):
            top = bottom - 0.15
            out.append(
                ReachStroke(
                    "LEFT" if j % 2 else "RIGHT",
                    z,
                    j,
                    j + 0.2,
                    (x, top),
                    (x, bottom),
                    ((x, top), (x, bottom - 0.07), (x, bottom)),
                )
            )
    return out


def test_measured_fit_has_pixel_floor_and_support():
    b = BodyReference(10.0, 0.36, 0.64, 0.20, 0.82, 0.9)
    result = fit_reach(strokes(), b, (560, 440))
    assert result["passed"], result["reasons"]
    assert result["dimensions_px"] == pytest.approx([72, 42])
    assert all(n == 6 for n in result["support"].values())
    ZoneRegistry.from_config(result["zones"])


def test_thin_envelope_is_refused_not_shrunk():
    thin = [replace(s, start=(s.start[0], 0.28), end=(s.end[0], 0.37)) for s in strokes()]
    result = fit_reach(thin, BodyReference(10.0, 0.36, 0.64, 0.2, 0.82, 0.9), (560, 440))
    assert not result["passed"]
    assert "VERTICAL_REACH_TOO_SMALL" in result["reasons"]
    assert not result["zones"]


@pytest.mark.parametrize("kind", ["MISSING", "UNCERTAIN"])
def test_uncertain_or_prior_tip_cannot_fit(kind):
    collector = StrokeCollector(ReachSettings())
    for i in range(100):
        collector.add(EndpointEvidence(i, i / 30, R, kind, "prior"), "snare")
    assert not collector.strokes


def test_product_view_preserves_camera_and_has_no_diagnostic_labels(config, monkeypatch):
    import cv2

    labels = []
    original = cv2.putText

    def put(image, text, *args, **kw):
        labels.append(text)
        return original(image, text, *args, **kw)

    monkeypatch.setattr(cv2, "putText", put)
    frame = np.full((480, 640, 3), 110, np.uint8)
    copy = frame.copy()
    out = render_kit(frame, Roi(40, 20, 560, 440), ZoneRegistry.from_config(config["zones"]))
    assert np.array_equal(frame, copy)
    assert out.shape == frame.shape
    assert not any(word in " ".join(labels) for word in ("VALID", "FPS", "confidence", "tracker"))
    assert all(label in labels for label in ("CRASH / RIDE", "HI-HAT", "SNARE", "TOM 1"))


def test_evidence_and_calibration_have_valid_additive_contracts():
    from spacedrums.calib.automatic import AutomaticCalibration
    from spacedrums.contracts.schema import validator

    e = EndpointEvidence(0, 1.0, R, "MEASURED", "SYNTHETIC", (0.2, 0.3), (0.2, 0.6), 0.9, 100.0)
    validator("endpoint-evidence").validate(e.to_dict())
    report = AutomaticCalibration((560, 440), provenance="SYNTHETIC").report()
    validator("product-calibration").validate(report)
    report["provenance"] = "PARTICIPANT_LIVE"
    assert list(validator("product-calibration").iter_errors(report))


def test_product_refuses_missing_measurement_provenance(config):
    reg = ZoneRegistry.from_config(config["zones"])
    pipeline = DecisionPipeline(
        config,
        registry=reg,
        session_id="SYNTHETIC",
        active_arm=Arm.A,
        hardware_id="test",
        config_hash=config_hash(config),
        audio=None,
        gain_fn=lambda z, v: 1.0,
    )
    sample, obs = build_sequence(reg, [], duration_s=0.1).frames[0]
    with pytest.raises(ValueError, match="EndpointEvidence"):
        pipeline.step(sample, obs, t_now=sample.t_frame_available)
