"""SYNTHETIC checks of the default ``redness`` red-tip path: cap detector + verifier + evidence tracker.

Images are rendered (``red_tip_synthetic``) and run through the real estimator, so pixels, not hand-made
blobs, are what is tracked. Real-footage accuracy is measured on labelled recordings, never here
(docs/perf/red-tip-stick-mode.md section 11).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spacedrums.contracts import FrameSample, FrameView, HandId, ImageRef, TimestampSource, TipMethod
from spacedrums.stick.red_tip import RedTipSettings
from spacedrums.stick.red_tip_caps import DEFAULT_VERIFIER, FEATURES, CapDetector, CapVerifier
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator
from spacedrums.stick.red_tip_synthetic import (
    background,
    draw_blob,
    draw_stick,
    draw_tip,
    path_frames,
    speckles,
)

L, R = HandId.LEFT, HandId.RIGHT
WALL = (160, 129, 66)  # the teal wall of the owner's recordings (BGR)
DARK_MAGENTA = {"hue": 150, "sat": 105, "val": 40, "radius": 5.5, "length": 13.0, "highlight": 0.3}
DARK_RED = {"hue": 174, "sat": 170, "val": 60, "radius": 5.5, "length": 13.0, "highlight": 0.3}


def wall(img, k):
    img[:] = background(rng=np.random.default_rng(k), bgr=WALL)


def run(frames, settings=None):
    """Per frame: (RedTipFrame, evidence, truth)."""
    est = RedTipEndpointEstimator(settings or RedTipSettings())
    out = []
    for view, truth in frames:
        est.observe(view)
        out.append((est.frame, dict(est.evidence), truth))
    return est, out


def owner(frame, truth, near=6.0):
    """The path each measured slot sits on (None: on no path)."""
    result = {}
    for h, st in frame.slots.items():
        if st.measured:
            d = sorted((math.dist(st.tip, p), name) for name, p in truth.items() if p is not None)
            result[h] = d[0][1] if d and d[0][0] <= near else None
    return result


def views(images, t0=100.0, dt=1 / 30):
    out = []
    for k, (img, truth) in enumerate(images):
        h, w = img.shape[:2]
        t = t0 + k * dt
        sample = FrameSample(frame_id=k, t_capture=t, t_frame_available=t + 0.004,
                             timestamp_source=TimestampSource.REPLAY, frame_size_px=(w, h),
                             roi_px=(0, 0, w, h), image_ref=ImageRef.memory(img),
                             camera_profile_id="synthetic-camera", dropped_since_last=0)
        out.append((FrameView(sample, img, img), truth))
    return out


def test_redness_is_the_default_detector_and_its_settings_are_validated():
    assert RedTipSettings().detector == "redness"
    assert RedTipSettings().as_dict()["redness_sigmas"] == [2.5, 4.5, 8.0]
    for bad in ({"detector": "hsv"}, {"region_level": 0.8}, {"redness_candidates": 1}, {"redness_sigmas": ()},
                {"release_evidence": 0.5, "bind_evidence": 0.4}, {"measure_quality": 1.5},
                {"challenge_frames": 0}, {"still_decay_s": 0.0}, {"evidence_alpha": 0.0}):
        with pytest.raises(ValueError):
            RedTipSettings(**bad)


def test_a_cap_pair_binds_with_the_image_right_tip_as_left_and_is_measured_on_the_caps():
    a = [(450 + k, 200 + 2 * k) for k in range(20)]  # image right = the player's left hand (camera view)
    b = [(180 - k, 260 - k) for k in range(20)]
    _, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.0))
    assert not any(st.measured for st in out[0][0].slots.values())  # a first sighting is never measured
    assert out[1][0].resets == {L, R}
    for frame, evidence, truth in out[1:]:
        assert owner(frame, truth) == {L: "a", R: "b"}
        for h in (L, R):
            assert evidence[h].kind == "MEASURED" and evidence[h].reason == "RED_TIP"
            assert evidence[h].confidence == 0.9
            assert math.dist(frame.slots[h].tip, truth["a" if h is L else "b"]) < 1.5
    assert not any(f.resets for f, *_ in out[2:])


@pytest.mark.parametrize("cap", [DARK_MAGENTA, DARK_RED], ids=["dark-magenta", "dark-red"])
def test_small_dark_caps_on_the_teal_wall_are_measured_at_playing_distance(cap):
    path = [(420.0 + 3 * k, 150.0 + 2 * k) for k in range(12)]
    _, out = run(path_frames({"a": path}, exposure_fraction=0.0, tip_kw=cap, decorate=wall))
    measured = [(f.slots[L], truth["a"]) for f, _, truth in out if f.slots[L].measured]
    assert len(measured) >= len(path) - 1
    assert all(math.dist(st.tip, p) < 2.0 for st, p in measured)
    assert not any(f.slots[R].measured for f, *_ in out)


@pytest.mark.parametrize("angle", [-80.0, -35.0, 0.0, 50.0])
def test_the_point_is_the_ball_centre_not_the_painted_neck_shaft_or_highlight(angle):
    cap = (320.4, 200.7)
    img = background(rng=np.random.default_rng(3), bgr=WALL)
    draw_stick(img, cap, angle_deg=angle, shaft_px=220, run_px=30, highlight=0.35, seed=4)
    blobs = CapDetector(RedTipSettings()).detect(img).blobs
    assert blobs and blobs[0].score > 0.8
    assert math.dist(blobs[0].center, cap) < 3.0  # the neck / run starts ~10 px from the centre
    assert all(math.dist(b.center, cap) > 40 or b is blobs[0] for b in blobs if b.score >= 0.35)
    assert blobs[0].outline and len(blobs[0].outline) >= 4


def test_a_fast_blurred_stroke_stays_measured_on_its_streak():
    path = [(300.0, 80.0 + 22 * k) for k in range(16)]
    _, out = run(path_frames({"a": path}, exposure_fraction=0.9))
    states = [f.slots[R].state for f, *_ in out[1:]]
    assert states.count("OBSERVED") >= len(states) - 1
    for k, (frame, _, truth) in enumerate(out[2:], start=2):
        st = frame.slots[R]
        if st.measured:  # on the exposure's streak from the previous position to the current one
            start = np.array(path[k]) + (np.array(path[k - 1]) - np.array(path[k])) * 0.9
            assert abs(st.tip[0] - 300.0) < 2.0 and start[1] - 3 <= st.tip[1] <= truth["a"][1] + 3


def test_a_strike_speed_streak_continues_as_weak_for_at_most_max_weak_frames():
    # 50 px per frame at 0.9 exposure on the orange-grey synthetic background: the verifier, fitted on still
    # caps, scores the streak near 0. The bound tip continues on it as WEAK (never longer than the limit),
    # then is trusted again once the stick stops.
    settings = RedTipSettings()
    path = [(300.0, 100.0)] * 6 + [(300.0, 100.0 + 50 * k) for k in range(1, 6)] + [(300.0, 350.0)] * 5
    _, out = run(path_frames({"a": path}, exposure_fraction=0.9), settings)
    states = [f.slots[R].state for f, *_ in out]
    assert states[1:6] == ["OBSERVED"] * 5 and states[11:] == ["OBSERVED"] * 5
    assert states[6:6 + settings.max_weak_frames] == ["WEAK"] * settings.max_weak_frames
    assert states[6 + settings.max_weak_frames] == "LOW_EVIDENCE"  # the limit: never measured beyond it
    for k in range(6, 6 + settings.max_weak_frames):
        frame, evidence, truth = out[k]
        assert evidence[R].reason == "RED_TIP_WEAK" and evidence[R].confidence == settings.weak_confidence
        start = path[k][1] - 0.9 * (path[k][1] - path[k - 1][1])
        tip = frame.slots[R].tip
        assert abs(tip[0] - 300.0) < 2.0 and start - 3 <= tip[1] <= truth["a"][1] + 3


def test_a_tip_reappearing_beyond_its_gate_is_adopted_without_restarting_its_stroke():
    a = [(470.0, 150.0 + 3 * k) for k in range(10)] + [None, None]
    a += [(470.0, 245.0 + 3 * k) for k in range(8)]
    b = [(180.0, 260.0)] * 20
    _, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.0))
    back = 12  # first frame after the dropout, ~70 px from where a was lost (beyond its 28 px gate)
    assert out[back][0].slots[L].measured and owner(out[back][0], out[back][2]) == {L: "a", R: "b"}
    assert not any(f.resets for f, *_ in out[3:])  # the other stick stayed in view: no identity restart
    for frame, _, truth in out[back:]:
        assert owner(frame, truth) == {L: "a", R: "b"}


def test_measured_tips_are_full_resolution_and_steady_on_slow_motion():
    # The half-res centre moves in 2 px steps; measured tips are re-measured at full resolution, so a cap
    # creeping 0.4 px per frame yields a smooth path (the stroke detector reads jitter as motion).
    path = [(300.3 + 0.4 * k, 200.6 + 0.3 * k) for k in range(30)]
    _, out = run(path_frames({"a": path}, exposure_fraction=0.0, tip_kw={"radius": 6.0, "length": 14.0}))
    tips = [(f.slots[R].tip, t["a"]) for f, _, t in out if f.slots[R].measured]
    assert len(tips) >= 28
    assert max(math.dist(tip, truth) for tip, truth in tips) < 1.0
    steps = [math.dist(a[0], b[0]) for a, b in zip(tips, tips[1:], strict=False)]
    assert max(steps) < 1.2  # true step 0.5 px; a half-res point jumps by 2 px


def test_a_red_reading_wooden_shaft_never_takes_the_cap_end_of_a_stick():
    # Under a warm lamp the shaft reads red too: shaft candidates join the cap's structure. The stick-end rule
    # decides only between cap-like parts, so the cap region is kept (it was once dropped for a shaft piece).
    for angle in (60.0, 80.0, 100.0):
        img = background(rng=np.random.default_rng(7), bgr=WALL)
        u = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
        cap = np.array([330.0, 160.0])
        draw_blob(img, tuple(cap + u * 120), 0, hue=15, sat=150, val=170, axes=(95, 5.5), angle_deg=angle)
        draw_blob(img, tuple(cap + u * 17), 0, hue=177, sat=200, val=150, axes=(12, 6.5), angle_deg=angle)
        draw_tip(img, tuple(cap), radius=5.5, length=12.0, angle_deg=angle, val=120, highlight=0.3)
        blobs = CapDetector(RedTipSettings()).detect(img).blobs
        assert any(math.dist(b.center, cap) < 20 and b.score > 0.8 for b in blobs)


def test_exposure_changes_keep_the_tip_measured():
    path = [(300.0 + 4 * k, 200.0) for k in range(18)]
    frames = path_frames({"a": path}, exposure_fraction=0.0)
    images = []
    for k, (view, truth) in enumerate(frames):
        gain = (1.0, 0.55, 0.35, 0.55, 1.0, 1.3)[k // 3]
        images.append((np.clip(view.full.astype(np.float32) * gain, 0, 255).astype(np.uint8), truth))
    _, out = run(views(images))
    assert sum(f.slots[R].measured for f, *_ in out) >= len(path) - 2
    assert all(math.dist(f.slots[R].tip, t["a"]) < 2.0 for f, _, t in out if f.slots[R].measured)


def test_a_hidden_tip_is_never_measured_and_comes_back_in_its_own_slot():
    a = [(470.0, 200.0 + 2 * k) if not 10 <= k < 14 else None for k in range(24)]
    b = [(180.0, 260.0 - 2 * k) for k in range(24)]
    _, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.0))
    for k in range(10, 14):
        frame, evidence, _ = out[k]
        assert not frame.slots[L].measured and frame.slots[L].tip is None
        assert evidence[L].tip is None  # a prediction never carries coordinates downstream
        assert owner(frame, out[k][2]) == {R: "b"}
    for frame, _, truth in out[15:]:
        assert owner(frame, truth) == {L: "a", R: "b"}


def test_crossing_tips_keep_their_identities():
    a = [(470 - 12 * k, 220) for k in range(30)]
    b = [(130 + 12 * k, 250) for k in range(30)]  # passes 30 px below a
    _, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.5))
    for frame, _, truth in out[1:]:
        assert set(owner(frame, truth).items()) <= {(L, "a"), (R, "b")}
    assert sum(f.slots[h].measured for f, *_ in out[1:] for h in (L, R)) >= 2 * 29 - 4


def test_tips_meeting_at_one_point_are_ambiguous_then_restarted_never_swapped():
    a = [(400 - 8 * k, 200) for k in range(10)] + [(320 + 8 * k, 200) for k in range(10)]
    b = [(240 + 8 * k, 200) for k in range(10)] + [(320 - 8 * k, 200) for k in range(10)]
    _, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.0))
    assert any(f.ambiguous or any(st.state == "AMBIGUOUS" for st in f.slots.values()) for f, *_ in out)
    for frame, _, truth in out[1:]:  # a measured slot is always on its own tip (never a fabricated swap)
        assert set(owner(frame, truth).items()) <= {(L, "a"), (R, "b")}
    ended = [k for k, (f, *_) in enumerate(out) if k and out[k - 1][0].ambiguous and not f.ambiguous]
    assert ended and out[ended[0]][0].resets == {L, R}


def test_a_static_red_object_never_keeps_a_slot_from_moving_sticks():
    def lamp(img, k):
        draw_blob(img, (590, 40), 9, hue=178, sat=220, val=190)

    a = [(460.0, 150.0 + 6 * k) for k in range(30)]
    b = [(180.0, 300.0 - 5 * k) for k in range(30)]
    est, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.3, decorate=lamp))
    for frame, _, truth in out[8:]:
        assert owner(frame, truth) == {L: "a", R: "b"}
    lamp_measured = [k for k, (f, *_) in enumerate(out) for st in f.slots.values()
                     if st.measured and math.dist(st.tip, (590, 40)) < 6]
    assert all(k < 8 for k in lamp_measured)


def test_skin_and_red_speckles_alone_are_never_measured():
    def clutter(img, k):
        draw_blob(img, (120 + 3 * k, 380), 24, hue=12, sat=95, val=170)  # a moving hand-sized skin blob
        draw_blob(img, (500, 400), 18, hue=8, sat=120, val=120, axes=(18, 30))
        speckles(img, np.random.default_rng(k), 40)

    _, out = run(path_frames({"none": [None] * 30}, decorate=clutter))
    assert not any(st.measured for f, *_ in out for st in f.slots.values())


def test_one_stick_alone_takes_its_side_and_the_other_slot_stays_empty():
    _, out = run(path_frames({"a": [(200.0 + 2 * k, 240.0) for k in range(20)]}, exposure_fraction=0.0))
    assert all(f.slots[L].state == "NO_TRACK" for f, *_ in out)
    assert sum(f.slots[R].measured for f, *_ in out) >= 19


def test_a_returning_tip_takes_the_slot_that_last_measured_it_not_its_image_side():
    # a is LEFT (larger x of the pair) at x = 340; both vanish, then a returns alone at x = 300 (image left
    # half, where the side rule alone would say RIGHT): identity memory keeps it LEFT.
    a = [(340.0, 200.0 + k) for k in range(10)] + [None] * 8 + [(300.0, 214.0 + k) for k in range(10)]
    b = [(180.0, 260.0 - k) for k in range(10)] + [None] * 18
    _, out = run(path_frames({"a": a, "b": b}, exposure_fraction=0.0))
    assert owner(out[5][0], out[5][2]) == {L: "a", R: "b"}
    for frame, _, truth in out[20:]:
        assert owner(frame, truth) == {L: "a"}


def test_a_tip_leaving_the_frame_is_never_measured_while_cut_and_is_reacquired_on_return():
    a = [(450.0, 120.0 - 15 * k) for k in range(12)] + [(450.0, -40.0 + 15 * k) for k in range(14)]
    _, out = run(path_frames({"a": a}, exposure_fraction=0.0))
    for frame, _, truth in out:
        st = frame.slots[L]
        p = truth["a"]
        if st.measured:
            assert p is not None and p[1] > 10 and math.dist(st.tip, p) < 2.0  # never a cut cap's point
    back = [k for k, (f, *_) in enumerate(out) if k >= 14 and f.slots[L].measured]
    first_visible = min(k for k in range(14, len(a)) if a[k][1] > 15)
    assert back and back[0] - first_visible <= 3


def test_a_long_gap_never_reemits_a_stale_point():
    settings = RedTipSettings()
    a = [(450.0, 200.0 + 2 * k) for k in range(8)] + [None] * 30
    _, out = run(path_frames({"a": a}, exposure_fraction=0.0), settings)
    gap = [f.slots[L] for f, *_ in out[8:]]
    assert not any(st.measured or st.tip is not None for st in gap)
    coasting = [st for st in gap if st.state == "PREDICTED"]
    assert len(coasting) <= round(settings.max_coast_s * 30) + 1
    assert gap[-1].state == "NO_TRACK"


def test_a_red_flash_in_a_single_frame_is_never_measured():
    flash = [None] * 5 + [(300.0, 200.0)] + [None] * 5
    _, out = run(path_frames({"a": flash}, exposure_fraction=0.0))
    assert not any(st.measured for f, *_ in out for st in f.slots.values())


def test_redness_records_carry_the_marker_label_and_the_verifier_quality():
    est, out = run(path_frames({"a": [(420.0, 200.0 + 3 * k) for k in range(6)]}, exposure_fraction=0.0))
    record = out[-1][0].to_record()
    assert record["candidates"] and 0.0 <= record["candidates"][0][7] <= 1.0
    assert record["slots"]["LEFT"]["state"] == "OBSERVED"
    summary = est.summary()
    assert summary["method_id"] == str(TipMethod.MARKER) and summary["settings"]["detector"] == "redness"
    assert summary["events"]["BINDS"] >= 1


def test_the_verifier_round_trips_validates_and_refits_from_examples():
    v = CapVerifier.from_dict(None)
    assert v.as_dict()["features"] == DEFAULT_VERIFIER["features"]
    assert CapVerifier.from_dict(v.as_dict()) == CapVerifier.from_dict(v.as_dict())
    with pytest.raises(ValueError, match="unknown"):
        CapVerifier.from_dict({**DEFAULT_VERIFIER, "features": ["colour"] * 7})
    with pytest.raises(ValueError, match="same"):
        CapVerifier.from_dict({**DEFAULT_VERIFIER, "weights": [1.0]})
    rng = np.random.default_rng(0)
    rows = rng.normal(0.0, 1.0, (200, len(FEATURES)))
    labels = (rows[:, FEATURES.index("response")] - rows[:, FEATURES.index("value")] > 0).astype(float)
    fitted = CapVerifier.fit(rows, labels, ["response", "value"])
    q = fitted.score(rows)
    assert ((q >= 0.5) == (labels == 1)).mean() > 0.95
    assert fitted.weights[0] > 0 > fitted.weights[1]
    with pytest.raises(ValueError, match="both"):
        CapVerifier.fit(rows, np.ones(200), ["response"])
    settings = RedTipSettings(verifier=fitted.as_dict())
    assert CapDetector(settings).verifier.features == ("response", "value")
