"""TEST-DATA-3: the guided recorder hooks (Task 06.1) — segment markers on the capture clock (half-open,
contiguous, every frame in exactly one take), timed and key-driven advance, re-take flags, skip, sync
markers, the post-segment quick check, deterministic output, and the cue drawing."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from spacedrums.contracts import HandId, TrackStatus
from spacedrums.data.metadata import SessionKind, SessionMetadata
from spacedrums.data.protocol import Protocol, SegmentSpec, SegmentType
from spacedrums.data.recorder import (
    GuidedRecorder,
    QuickCheckThresholds,
    SegmentStats,
    quick_check,
    segment_frame_ranges,
)
from spacedrums.geometry import ZoneRegistry

ZONES = [
    {
        "zone_id": "snare",
        "name": "Snare",
        "trigger_type": "HAND_TIP",
        "shape": {"type": "ELLIPSE", "center": [0.4, 0.6], "rx": 0.15, "ry": 0.1, "angle_rad": 0.0},
        "impact_surface": {
            "type": "ARC",
            "center": [0.4, 0.6],
            "rx": 0.15,
            "ry": 0.1,
            "angle_rad": 0.0,
            "theta_start_rad": 3.141592653589793,
            "theta_end_rad": 6.283185307179586,
        },
        "inward_normal": [0.0, 1.0],
        "sample_id": "s",
        "gain_curve_id": "default",
    },
]


@dataclass
class _Sample:
    t_capture: float
    dropped_since_last: int = 0


def _result(left: str = "VALID", right: str = "VALID"):
    mk = lambda st: SimpleNamespace(track=SimpleNamespace(status=st))  # noqa: E731
    return SimpleNamespace(hands={HandId.LEFT: mk(left), HandId.RIGHT: mk(right)})


def _protocol() -> Protocol:
    segs = (
        SegmentSpec("a", SegmentType.SINGLE_HITS, "A", 1.0, zone_ids=("snare",), hands=(HandId.RIGHT,)),
        SegmentSpec("b", SegmentType.FAKE_SWING, "B", 0.5, zone_ids=("snare",)),
        SegmentSpec(
            "c",
            SegmentType.PAD_MIC,
            "C",
            0.5,
            zone_ids=("snare",),
            condition="PAD",
            pad_zone_id="snare",
            core=False,
            optional=True,
        ),
    )
    return Protocol(
        "p", "t", segs, ("snare",), 0, "explicit", {"primary_zone": "snare", "secondary_zone": "snare"}
    )


def _meta(pad: bool = False) -> SessionMetadata:
    return SessionMetadata.new(
        kind=SessionKind.SYNTHETIC,
        session_id="synthetic-r",
        participant_id="SYNTHETIC",
        session_index=1,
        date="2026-09-21",
        started_at="2026-09-21T00:00:00+00:00",
        t_mono_at_start=10.0,
        hardware_id="HW-01",
        camera_profile_id="synthetic-camera",
        audio_profile_id="a",
        roi_px=(0, 0, 10, 10),
        config_hash="sha256:" + "0" * 64,
        git_sha="a" * 40,
        clock_id="perf_counter",
        zone_layout_id="z",
        arm_active="A",
        arms_shadow=["B"],
        tip_method_active="GEOM",
        protocol=None,
        source={"kind": "SYNTHETIC", "detail": {}},
        video={
            "container": "PNG_SEQUENCE",
            "codec": "png",
            "lossless": True,
            "crop": "FULL",
            "frame_size_px": [10, 10],
            "parameters": {},
        },
        pad_zone_id="snare" if pad else None,
    )


def _drive(
    rec: GuidedRecorder,
    n: int,
    dt: float = 0.1,
    t0: float = 10.0,
    keys: dict[int, str] | None = None,
    statuses=None,
):
    ts = []
    for k in range(n):
        t = t0 + k * dt
        ts.append(t)
        if keys and k in keys:
            rec.on_key(keys[k])
        st = statuses(k) if statuses else _result()
        rec.on_frame(_Sample(t, 1 if k == 3 else 0), st)
    rec.finish()
    return ts


def test_timed_advance_gives_contiguous_half_open_markers_and_each_frame_one_take():
    meta = _meta()
    rec = GuidedRecorder(_protocol(), meta, log=None)
    ts = _drive(rec, 20)  # 2.0 s covers a (1.0) + b (0.5) with 0.5 s to spare (c optional, disabled)
    segs = meta.data["segments"]
    assert [s["segment_id"] for s in segs] == ["a", "b"]
    assert segs[0]["t_start"] == 10.0 and segs[0]["t_end"] == segs[1]["t_start"]
    assert all(s["status"] == "RECORDED" and s["quick_check"] is not None for s in segs)
    ranges = segment_frame_ranges(segs, ts)
    covered = [i for (lo, hi) in ranges.values() for i in range(lo, hi)]
    assert covered == sorted(covered) and len(covered) == len(set(covered))
    assert ranges[("a", 1)] == (0, 10) and ranges[("b", 1)] == (10, 15)
    assert segs[0]["quick_check"]["n_frames"] == 10 and segs[0]["quick_check"]["dropped"] == 1
    assert abs(segs[0]["quick_check"]["fps_est"] - 10.0) < 1e-6
    assert meta.errors() == []
    assert rec.done and "finished" in rec.status_lines()[0]


def test_keys_next_retake_skip_and_sync_marker():
    meta = _meta(pad=True)
    rec = GuidedRecorder(_protocol(), meta, enable_optional=True, log=None)
    # frame 2: retake a; frame 5: next (to b); frame 6: skip b (to c); frame 8: sync marker; frame 9: fallback
    _drive(rec, 12, keys={2: "r", 5: "n", 6: "k", 8: "m", 9: "f"})
    segs = meta.data["segments"]
    ids = [(s["segment_id"], s["take"], s["status"]) for s in segs]
    assert ids[0] == ("a", 1, "RETAKEN") and ids[1] == ("a", 2, "RECORDED")
    assert ids[2] == ("b", 1, "SKIPPED") and ids[3][0] == "c" and ids[3][2] == "RECORDED"
    assert segs[3]["condition"] == "PAD" and segs[3]["pad_zone_id"] == "snare"
    markers = meta.data["pad_mic"]["sync_markers"]
    assert len(markers) == 1 and markers[0]["segment_id"] == "c" and markers[0]["kind"] == "CLAP"
    assert markers[0]["t_mono"] == 10.0 + 8 * 0.1
    assert len(meta.data["fallback_events"]) == 1
    assert meta.errors() == []
    assert rec.status_lines()[0].startswith("protocol finished")


def test_finish_includes_the_last_frame_and_flags_an_open_take():
    meta = _meta()
    rec = GuidedRecorder(_protocol(), meta, log=None)
    ts = _drive(rec, 4)  # protocol not finished: segment a still open at the end
    seg = meta.data["segments"][0]
    assert seg["status"] == "RECORDED" and seg["t_end"] > ts[-1]  # last frame belongs to the take
    assert segment_frame_ranges(meta.data["segments"], ts)[("a", 1)] == (0, 4)
    rec2 = GuidedRecorder(_protocol(), _meta(), log=None)
    rec2.finish()  # no frame at all
    assert rec2.done and rec2.meta.data["segments"] == []


def test_quick_check_thresholds_and_no_frames():
    th = QuickCheckThresholds(q_seg=0.6, nominal_fps=10.0, fps_tolerance=0.15, max_drops=1)
    spec = SegmentSpec("a", SegmentType.SINGLE_HITS, "A", 1.0, hands=(HandId.RIGHT,))
    st = SegmentStats()
    assert quick_check(st, spec, th)["verdict"] == "NO_FRAMES"
    for k in range(10):
        st.add(k * 0.1, 0, {HandId.LEFT: TrackStatus.INVALID, HandId.RIGHT: TrackStatus.VALID})
    qc = quick_check(st, spec, th)
    assert qc["verdict"] == "OK" and qc["tracking_validity"] == {"LEFT": 0.0, "RIGHT": 1.0}
    assert abs(qc["fps_est"] - 10.0) < 1e-6
    both = SegmentSpec("b", SegmentType.SINGLE_HITS, "B", 1.0)  # both hands relevant -> LEFT 0.0 fails
    assert quick_check(st, both, th)["verdict"] == "REVIEW"
    st.dropped = 5
    assert quick_check(st, spec, th)["verdict"] == "REVIEW"


def test_recorder_is_deterministic_and_validity_uses_track_status():
    def statuses(k):
        return _result(right="INVALID" if k % 2 else "VALID")

    outs = []
    for _ in range(2):
        meta = _meta()
        rec = GuidedRecorder(_protocol(), meta, log=None)
        _drive(rec, 20, statuses=statuses)
        outs.append(meta.to_dict()["segments"])
    assert outs[0] == outs[1]
    qc = outs[0][0]["quick_check"]
    assert qc["tracking_validity"]["RIGHT"] == 0.5 and qc["tracking_validity"]["LEFT"] == 1.0
    assert qc["verdict"] == "REVIEW"  # RIGHT is the relevant hand of segment a


def test_draw_cues_marks_the_cued_zone_and_countdown():
    registry = ZoneRegistry.from_config(ZONES)
    meta = _meta()
    rec = GuidedRecorder(_protocol(), meta, log=None)
    img = np.zeros((100, 100, 3), np.uint8)
    rec.draw_cues(img, registry)  # before the first frame: nothing drawn
    assert not img.any()
    rec.on_frame(_Sample(10.0), _result())
    rec.draw_cues(img, registry)
    assert img.any()
    assert any("A" in line for line in rec.status_lines())
