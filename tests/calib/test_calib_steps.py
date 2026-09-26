"""Tasks 14.2 / 14.3 / 14.5 unit tests of the step accumulators (hand-built SYNTHETIC frames)."""

import pytest

from spacedrums.calib.steps import (
    CameraCheck,
    PlayingArea,
    StickPrior,
    StickSample,
    ValidationSchedule,
    ValidationStrikes,
    WizardFrame,
    hand_span_px,
)
from spacedrums.calib.wizard import WizardSettings
from spacedrums.capture import Roi
from spacedrums.contracts import (
    Arm,
    CandidateDerivation,
    CandidateSource,
    CommittedStrike,
    FrameSample,
    HandId,
    HandObservation,
    ImageRef,
    TimestampSource,
    TrackState,
)
from spacedrums.hands.grip import GripSettings

ST = WizardSettings().to_dict()
ROI = Roi(40, 20, 560, 440)
L, R = HandId.LEFT, HandId.RIGHT


def sample(k, t, *, profile="hw01-integrated-webcam-v0", size=(640, 480), roi=(40, 20, 560, 440), dropped=0):
    return FrameSample(
        frame_id=k,
        t_capture=t,
        t_frame_available=t + 0.004,
        timestamp_source=TimestampSource.REPLAY,
        frame_size_px=size,
        roi_px=roi,
        image_ref=ImageRef.memory(None),
        camera_profile_id=profile,
        dropped_since_last=dropped,
    )


def hand(k, t, h, wrist, span_px=30.0):
    sy, sx = span_px / 440, 0.35 * span_px / 560
    lm = [(wrist[0], wrist[1] - sy * 0.5)] * 21
    lm[0], lm[9] = wrist, (wrist[0], wrist[1] - sy)
    lm[5], lm[17] = (wrist[0] - sx, wrist[1] - 0.95 * sy), (wrist[0] + sx, wrist[1] - 0.85 * sy)
    return HandObservation(
        frame_id=k,
        t_capture=t,
        hand_id=h,
        present=True,
        detector_id="t",
        landmarks=tuple(lm),
        landmark_visibility=None,
        handedness_score=0.9,
        bbox=(0.0, 0.0, 0.1, 0.1),
    )


def track(k, t, h, status="VALID", tip=(0.5, 0.3), v=(0.0, 0.0)):
    live = status in ("VALID", "DEGRADED")
    return TrackState(
        frame_id=k,
        t_capture=t,
        hand_id=h,
        status=status,
        tracker_id="t",
        tip_method="GEOM",
        tip_filtered=tip if live else None,
        tip_velocity=v if live else None,
        tip_acceleration=None,
        axis_angle=None,
        axis_angular_velocity=None,
        confidence=0.9 if live else 0.0,
        frames_since_valid=0 if status == "VALID" else 1,
        last_valid_t=t if live else None,
        history_ref=None,
        reset_reason=None,
    )


def frame(
    k,
    t,
    *,
    wrists=None,
    spans=(30.0, 30.0),
    status=("VALID", "VALID"),
    support=(0.28, 0.26),
    conf=0.8,
    v=(0.0, 0.0),
    commits=(),
    gray=None,
    **kw,
):
    wrists = wrists or {L: (0.35, 0.6), R: (0.65, 0.6)}
    hands = {L: hand(k, t, L, wrists[L], spans[0]), R: hand(k, t, R, wrists[R], spans[1])}
    tracks = {L: track(k, t, L, status[0], v=v), R: track(k, t, R, status[1], v=v)}
    sticks = {L: StickSample(support[0], conf), R: StickSample(support[1], conf)}
    return WizardFrame(sample(k, t, **kw), hands, sticks, tracks, tuple(commits), gray)


def test_hand_span_matches_the_task_03_3_baseline():
    assert hand_span_px(hand(0, 0.0, L, (0.4, 0.6), 30.0), ROI, GripSettings()) == pytest.approx(30.0)


def test_camera_check():
    expected = {
        "camera_profile_id": "hw01-integrated-webcam-v0",
        "resolution_px": [640, 480],
        "roi_px": [40, 20, 560, 440],
        "requested_fps": 30,
    }
    ok = CameraCheck(0.0, expected, ST)
    for k in range(91):
        ok.feed(frame(k, k / 30, gray=120.0))
    r = ok.result()
    assert r["passed"] and r["delivered_fps_median"] == pytest.approx(30.0) and r["exposure_advice"] == "OK"
    slow = CameraCheck(0.0, expected, ST)
    for k in range(40):
        slow.feed(frame(k, k / 10, gray=30.0, profile="other", dropped=1))
    r = slow.result()
    assert not r["acceptable"] and any("camera_profile_id" in m for m in r["mismatches"])
    assert r["exposure_advice"] == "TOO_DARK" and r["dropped_total"] == 39
    assert any("differs from the requested" in w for w in r["warnings"])
    assert "NOT a native-FPS measurement" in r["label"]


def test_playing_area_coverage_and_distance_advice():
    pa = PlayingArea(0.0, ST, ROI, GripSettings())
    for k in range(150):
        x = 0.05 + 0.9 * (k % 50) / 49
        pa.feed(frame(k, k / 30, wrists={L: (x, 0.6), R: (1 - x, 0.6)}))
    r = pa.result()
    assert r["passed"] and r["distance_advice"] == "OK" and r["both_valid_fraction"] == 1.0
    assert all(s["valid_frames"] >= 5 for s in r["subregions"])
    far = PlayingArea(0.0, ST, ROI, GripSettings())
    for k in range(30):
        far.feed(frame(k, k / 30, spans=(15.0, 16.0), status=("VALID", "INVALID")))
    r = far.result()
    assert not r["passed"] and r["distance_advice"] == "MOVE_CLOSER" and r["both_valid_fraction"] == 0.0
    near = PlayingArea(0.0, ST, ROI, GripSettings())
    near.feed(frame(0, 0.0, spans=(60.0, 60.0)))
    assert near.result()["distance_advice"] == "MOVE_FARTHER"


def test_stick_prior_median_and_rejections():
    sp = StickPrior(0.0, ST, 0.27)
    for k in range(60):
        sp.feed(frame(k, k / 30, support=(0.28 + 0.001 * (k % 3), 0.25)))
    for k in range(60, 70):
        sp.feed(frame(k, k / 30, v=(0.5, 0.0)))  # moving: rejected
    for k in range(70, 75):
        sp.feed(frame(k, k / 30, conf=0.3))  # weak axis: rejected
    for k in range(75, 78):
        sp.feed(frame(k, k / 30, support=(0.0, None)))  # no extent / no axis: rejected
    r = sp.result()
    assert r["passed"] and r["l_prior"] == {"LEFT": pytest.approx(0.281), "RIGHT": 0.25}
    assert r["per_hand"]["LEFT"]["n_rejected"]["moving"] == 10
    assert r["per_hand"]["LEFT"]["n_rejected"]["low_axis_confidence"] == 5
    assert (
        r["per_hand"]["LEFT"]["n_rejected"]["no_axis"] == 3 == r["per_hand"]["RIGHT"]["n_rejected"]["no_axis"]
    )


def test_stick_prior_falls_back_to_the_default():
    sp = StickPrior(0.0, ST, 0.27)
    for k in range(40):
        sp.feed(frame(k, k / 30, support=(0.9, 0.27 if k % 2 else 0.20)))
    r = sp.result()
    assert r["per_hand"]["LEFT"]["source"] == "DEFAULT" and r["l_prior"]["LEFT"] == 0.27
    assert any("sanity range" in w for w in r["per_hand"]["LEFT"]["warnings"])
    assert r["per_hand"]["RIGHT"]["source"] == "DEFAULT"  # unstable (IQR)
    assert not r["passed"]


def commit(zone, t, hand_id=L, arm="A", shadow=False, k=0):
    return CommittedStrike(
        strike_id=f"s{k}",
        candidate_id=f"c{k}",
        frame_id=k,
        t_capture=t,
        hand_id=hand_id,
        zone_id=zone,
        source=CandidateSource.REACTIVE if arm == "A" else CandidateSource.RULE,
        derivation=CandidateDerivation.GEOMETRY,
        arm=Arm(arm),
        shadow=shadow,
        t_commit=t,
        t_impact_target=t,
        intensity_proxy=1.0,
        gain=1.0,
        refractory_until=t + 0.1,
        episode_id=f"e{k}",
        commit_policy_id="commit-v1",
    )


def test_validation_schedule_and_counts():
    st = {**ST, "strikes_per_zone": 2, "cue_period_s": 1.0, "validation_lead_in_s": 0.5}
    sched = ValidationSchedule(("hihat", "snare"), 10.0, 2, 1.0, 0.5)
    assert [c.zone_id for c in sched.cues] == ["hihat", "hihat", "snare", "snare"]
    assert sched.at(10.6).zone_id == "hihat" and sched.at(12.6).zone_id == "snare" and sched.at(10.2) is None
    v = ValidationStrikes(
        10.0, st, ["hihat", "snare"], near_pairs=[{"zones": ["hihat", "snare"], "gap": 0.005}]
    )
    commits = [
        commit("hihat", 11.0, k=1),
        commit("hihat", 11.2, k=2),  # duplicate in cue 1
        commit("snare", 12.8, k=3),
        commit("hihat", 13.9, k=4),  # snare cue 2: wrong zone
        commit("snare", 13.0, k=5, arm="B"),
        commit("snare", 20.0, k=6),
        commit("hihat", 11.9, shadow=True),
    ]
    for i, c in enumerate(commits):
        v.feed(frame(i, c.t_capture, commits=[c]))
    r = v.result()
    rows = {row["zone_id"]: row for row in r["per_zone"]}
    assert rows["hihat"]["detected"] == 1 and rows["hihat"]["extra_commits"] == 1
    assert set(rows["hihat"]["flags"]) == {"LOW_DETECTION", "DUPLICATES", "NEAR_NEIGHBOUR"}
    assert rows["snare"]["detected"] == 1 and rows["snare"]["wrong_zone_commits"] == 1
    assert "CROSS_TALK" in rows["snare"]["flags"]
    assert not r["passed"] and any("outside every cue window" in f for f in r["flags"])
