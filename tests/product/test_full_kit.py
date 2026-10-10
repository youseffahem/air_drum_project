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


# -- realistic arrangement (display coordinates; x is the pad centre, y the top strike edge) -------


def _pads(cfg):
    return {p["zone_id"]: p for p in cfg["product"]["developer_demo"]["pads"]}


def test_kit_is_arranged_like_a_drum_kit_from_the_players_seat(cfg):
    p = _pads(cfg)

    def edge(z):
        return p[z]["y"]

    def bottom(z):
        return p[z]["y"] + p[z]["height"]

    # cymbals are the highest pieces, crash on the left and ride on the right
    assert max(edge("crash"), edge("ride")) < min(edge(z) for z in ("tom1", "tom2", "hihat", "snare",
        "floor_tom"))
    assert p["crash"]["x"] < p["tom1"]["x"] < p["tom2"]["x"] < p["ride"]["x"]
    # hi-hat on the player's left, below the crash and in front of (higher than) the snare
    assert p["hihat"]["x"] < p["snare"]["x"] and bottom("crash") < edge("hihat") < edge("snare")
    # rack toms sit above the snare / floor tom, tom2 right of and a little higher than tom1
    assert max(bottom("tom1"), bottom("tom2")) < min(edge("snare"), edge("floor_tom"))
    assert p["tom1"]["x"] < p["tom2"]["x"] and edge("tom2") < edge("tom1")
    assert abs(p["tom1"]["x"] - p["snare"]["x"]) < 0.1  # above the snare, slightly right of it
    # the floor tom is lower right, beside the snare, with tom2 above it
    assert p["floor_tom"]["x"] > p["snare"]["x"] and abs(p["tom2"]["x"] - p["floor_tom"]["x"]) < 0.2


def test_cymbals_look_different_from_drum_heads_and_hit_targets_are_large(cfg):
    p = _pads(cfg)
    w, h = cfg["roi"]["px"][2:]
    drums = ("tom1", "tom2", "snare", "floor_tom")
    for z in ("crash", "ride", "hihat"):
        assert p[z]["width"] / p[z]["height"] > 1.9  # wide, shallow plates
    for z in drums:
        assert p[z]["width"] / p[z]["height"] < 1.9  # deeper drum heads
        assert p[z]["width"] * w >= 90 and p[z]["height"] * h >= 50  # well above the 72 x 42 px floor
    area = {z: p[z]["width"] * p[z]["height"] for z in p}
    assert area["floor_tom"] == max(area[z] for z in drums)
    assert area["snare"] > area["tom1"] and area["snare"] > area["tom2"]


def test_every_pair_clears_the_gap_floors_including_diagonals(cfg):
    from spacedrums.geometry.kit_layout import kit_clearance_failures

    s = ReachSettings(**cfg["product"]["reach"])
    pads = list(_pads(cfg).values())
    assert kit_clearance_failures(pads, tuple(cfg["roi"]["px"][2:]), s.horizontal_gap_px,
        s.vertical_gap_px) == []


def test_mirrored_zone_geometry_matches_the_display_layout(cfg):
    p = _pads(cfg)
    for z in cfg["zones"]:
        pad = p[z["zone_id"]]
        xs = [q[0] for q in z["shape"]["points"]]
        ys = [q[1] for q in z["shape"]["points"]]
        # camera x = 1 - display x; the polygon spans exactly the configured pad
        assert min(xs) == pytest.approx(1 - pad["x"] - pad["width"] / 2, abs=1e-9)
        assert max(xs) == pytest.approx(1 - pad["x"] + pad["width"] / 2, abs=1e-9)
        assert min(ys) == pytest.approx(pad["y"], abs=1e-9)
        assert max(ys) == pytest.approx(pad["y"] + pad["height"], abs=1e-9)
        assert z["impact_surface"]["p0"][1] == z["impact_surface"]["p1"][1] == pytest.approx(pad["y"])


def test_saved_kit_layout_replaces_the_configured_pads(tmp_path):
    from spacedrums.geometry.kit_layout import save_pads, transform_pads

    base = play.play_config(demo=True, kit="full")
    moved = transform_pads(base["product"]["developer_demo"]["pads"], dx=0.01)
    path = tmp_path / "kit-layout.yaml"
    save_pads(path, moved)
    cfg = play.play_config(demo=True, kit="full", kit_layout=path)
    assert cfg["product"]["developer_demo"]["source"] == str(path)
    old = {z["zone_id"]: z["shape"]["points"][0][0] for z in base["zones"]}
    new = {z["zone_id"]: z["shape"]["points"][0][0] for z in cfg["zones"]}
    assert all(new[k] == pytest.approx(old[k] - 0.01, abs=1e-4) for k in old)  # display +x is camera -x
    too_far = tmp_path / "too-far.yaml"
    save_pads(too_far, transform_pads(moved, dx=0.5))
    with pytest.raises(ValueError):
        play.play_config(demo=True, kit="full", kit_layout=too_far)
    bunched = tmp_path / "bunched.yaml"
    save_pads(bunched, transform_pads(base["product"]["developer_demo"]["pads"], scale=1.25))
    with pytest.raises(ValueError):
        play.play_config(demo=True, kit="full", kit_layout=bunched)


def test_kit_layout_flags_need_the_full_kit_demo():
    for argv in (["--layout-preview"], ["--kit-layout", "x.yaml"], ["--demo", "--kit", "four",
        "--layout-preview"]):
        with pytest.raises(SystemExit):
            play.main(argv)


def test_four_pad_kit_is_unchanged_by_the_full_kit_layout():
    cfg = play.play_config(demo=True, kit="four")
    assert [z["zone_id"] for z in cfg["zones"]] == ["crash_ride", "hihat", "snare", "tom1"]
    assert cfg["product"]["developer_demo"]["profile_id"] == "professor-fixed-guide-v1"
