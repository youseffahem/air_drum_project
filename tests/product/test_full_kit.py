"""SYNTHETIC full-kit regressions: layout geometry and one-sound-per-stroke on all seven pads."""

from dataclasses import replace

import numpy as np
import pytest

from spacedrums.app import play
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.calib.developer_demo import DeveloperDemoLayout
from spacedrums.calib.reach import ReachSettings
from spacedrums.config import config_hash
from spacedrums.contracts import Arm, HandId, TipMethod
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.kit_layout import KIT_NAMES, KIT_SAMPLES, kit_layout

L, R = HandId.LEFT, HandId.RIGHT
IDS = ["crash", "tom1", "tom2", "ride", "hihat", "snare", "floor_tom"]


@pytest.fixture(scope="module")
def cfg():
    return play.play_config(demo=True, kit="full")


def run(cfg, sequence):
    audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=False, clock=lambda: 100.0)
    pipeline = DecisionPipeline(
        cfg, registry=ZoneRegistry.from_config(cfg["zones"]), session_id="SYNTHETIC", active_arm=Arm.A,
        hardware_id="test", config_hash=config_hash(cfg), audio=audio, developer_demo=True,
    )
    results = []
    for s, o in sequence:
        observations = {
            h: (hand, replace(stick, method_id=TipMethod.AXIS_REFINED)) for h, (hand, stick) in o.items()
        }
        evidence = {
            h: EndpointEvidence(s.frame_id, s.t_capture, h, "MEASURED" if stick.present else "MISSING",
                                "SYNTHETIC", stick.tip, stick.axis_origin, stick.tip_confidence)
            for h, (_, stick) in observations.items()
        }
        results.append(pipeline.step(s, observations, t_now=s.t_frame_available, endpoint_evidence=evidence))
    return results, audio


def test_layout_has_every_piece_inside_the_roi_and_clear_of_each_other(cfg):
    zones = cfg["zones"]
    assert sorted(z["zone_id"] for z in zones) == sorted(IDS)
    assert {z["zone_id"]: z["sample_id"] for z in zones} == KIT_SAMPLES
    assert {z["zone_id"]: z["name"] for z in zones} == KIT_NAMES
    for z in zones:
        xs, ys = zip(*z["shape"]["points"], strict=True)
        assert 0 <= min(xs) and max(xs) <= 1 and 0 <= min(ys) and max(ys) <= 1
    # Mirrored display: the display-left hi-hat is on the camera's right, crash display-left too.
    centre = {z["zone_id"]: np.mean([p[0] for p in z["shape"]["points"]]) for z in zones}
    assert centre["hihat"] > centre["snare"] > centre["floor_tom"]
    assert centre["crash"] > centre["tom1"] > centre["tom2"] > centre["ride"]


def test_demo_layout_keeps_product_pad_floors(cfg):
    layout = DeveloperDemoLayout(cfg)
    s = ReachSettings(**cfg["product"]["reach"])
    w, h = layout.roi_size
    for pad in cfg["product"]["developer_demo"]["pads"]:
        assert pad["width"] * w >= s.min_width_px and pad["height"] * h >= s.min_height_px


def test_layout_rejects_overlap_unknown_and_offscreen_pads():
    pad = {"zone_id": "snare", "x": 0.5, "y": 0.5, "width": 0.2, "height": 0.1}
    with pytest.raises(ValueError, match="overlap"):
        kit_layout([pad, {**pad, "zone_id": "tom1", "x": 0.55}])
    with pytest.raises(ValueError, match="unknown"):
        kit_layout([{**pad, "zone_id": "kick"}])
    with pytest.raises(ValueError, match="inside"):
        kit_layout([{**pad, "x": 0.95}])
    with pytest.raises(ValueError, match="duplicate"):
        kit_layout([pad, {**pad, "x": 0.9}])


@pytest.mark.parametrize("hand", [L, R])
@pytest.mark.parametrize("zone", IDS)
def test_either_hand_hits_each_piece_once_with_its_own_sample(cfg, hand, zone):
    reg = ZoneRegistry.from_config(cfg["zones"])
    seq = build_sequence(reg, [Swing(hand, zone, 0.3)], duration_s=1.1)
    results, audio = run(cfg, seq.frames)
    commits = [c for r in results for c in r.commits]
    events = [e for r in results for e in r.audio]
    assert [(c.hand_id, c.zone_id) for c in commits] == [(hand, zone)]
    assert len(events) == audio.events == 1 and events[0].sample_id == KIT_SAMPLES[zone]


def test_a_run_around_the_kit_sounds_each_piece_in_order(cfg):
    reg = ZoneRegistry.from_config(cfg["zones"])
    swings = [Swing(R if i % 2 else L, z, 0.3 + i * 0.5) for i, z in enumerate(IDS)]
    results, _ = run(cfg, build_sequence(reg, swings, duration_s=0.3 + len(IDS) * 0.5 + 0.5).frames)
    assert [c.zone_id for r in results for c in r.commits] == IDS


# -- stroke look-ahead ---------------------------------------------------------------------------


def _engine(cfg, lead_s):
    from spacedrums.geometry.strokes import MeasuredStrokeGeometry, StrokeSettings

    return MeasuredStrokeGeometry(ZoneRegistry.from_config(cfg["zones"]), v_min=0.15,
                                  settings=StrokeSettings(lead_s=lead_s))


def _feed(engine, points):
    from spacedrums.contracts import TrackStatus

    out = []
    for i, point in enumerate(points):
        out.extend(engine.observe(frame_id=i, t_capture=i / 30, hand_id=R, position=point,
                                  status=TrackStatus.VALID, t_candidate=i / 30))
    return out


def _snare_edge(cfg):
    zone = next(z for z in cfg["zones"] if z["zone_id"] == "snare")
    return zone["impact_surface"]["p0"][1], sum(zone["impact_surface"][k][0] for k in ("p0", "p1")) / 2


def test_lead_fires_one_frame_before_the_crossing_and_only_once(cfg):
    edge_y, x = _snare_edge(cfg)
    ys = [edge_y - 0.20 + 0.03 * i for i in range(7)]  # 0.9 ROI/s downward, last sample 0.02 above the edge
    path = [(x, y) for y in ys] + [(x, ys[-1] + 0.03), (x, ys[-1] + 0.06)]
    assert ys[-1] < edge_y < ys[-1] + 0.03
    strict, early = _feed(_engine(cfg, 0.0), path), _feed(_engine(cfg, 0.033), path)
    assert [c.zone_id for c in strict] == [c.zone_id for c in early] == ["snare"]
    assert early[0].frame_id == strict[0].frame_id - 1
    assert early[0].t_impact_est == pytest.approx(early[0].t_capture)


def test_lead_needs_a_sustained_fast_downstroke(cfg):
    edge_y, x = _snare_edge(cfg)
    slow = [(x, edge_y - 0.06 + 0.002 * i) for i in range(15)]  # creeping toward the edge
    hover = [(x, edge_y - 0.01)] * 10  # stopped just above it
    one_sample = [(x, edge_y - 0.20)] * 4 + [(x, edge_y - 0.05)]  # a single fast sample is not sustained
    for path in (slow, hover, one_sample):
        assert not _feed(_engine(cfg, 0.033), path)
