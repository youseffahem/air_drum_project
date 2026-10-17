"""SYNTHETIC two-tip tracking: identities, crossings, rolls, occlusion, prediction expiry, distractors, blur.

Every test renders red tips along explicit pixel paths (``red_tip_synthetic.path_frames``) and runs the real
detector + tracker + contract adapter, so the images, not hand-made blobs, are what is tracked. These cover
the ``detector: colour`` path (HSV segmentation + RedTipTracker); the default ``redness`` path (cap detector
+ evidence tracker) is covered in test_red_tip_evidence.py.
"""

import math

import numpy as np
import pytest
from test_estimators import _fist_landmarks

from spacedrums.contracts import HandId, HandObservation, TipMethod
from spacedrums.stick.red_tip import RedTipSettings
from spacedrums.stick.red_tip_estimator import RedTipEndpointEstimator
from spacedrums.stick.red_tip_synthetic import REAL_CAP, draw_blob, draw_tip, path_frames, speckles

L, R = HandId.LEFT, HandId.RIGHT


def track(paths, settings=None, hands=None, **kw):
    """Per frame: (RedTipFrame, evidence, observations, truth)."""
    est = RedTipEndpointEstimator(settings or RedTipSettings(detector="colour"))
    out = []
    for view, truth in path_frames(paths, **kw):
        obs = est.observe(view, hands(view) if hands else None)
        out.append((est.frame, dict(est.evidence), obs, truth))
    return est, out


def owner(frame, truth):
    """The path each measured slot follows: the nearer path, or None when neither is within 6 px."""
    result = {}
    for h, st in frame.slots.items():
        if st.measured:
            near = sorted((math.dist(st.tip, p), name) for name, p in truth.items() if p is not None)
            result[h] = near[0][1] if near and near[0][0] <= 6 else None
    return result


def swapped(out, expected):
    """Frames where a measured slot sits on a path other than its expected one (a fabricated swap)."""
    bad = []
    for k, (frame, _, _, truth) in enumerate(out):
        for h, name in owner(frame, truth).items():
            if name is not None and h in expected and name != expected[h]:
                bad.append((k, h, name))
    return bad


def test_two_tips_bind_after_two_frames_with_the_image_right_tip_as_left():
    a = [(450 + k, 200 + 2 * k) for k in range(20)]  # image right = the player's left hand (camera view)
    b = [(180 - k, 260 - k) for k in range(20)]
    est, out = track({"a": a, "b": b}, exposure_fraction=0.0)
    assert all(e.kind == "MISSING" and e.tip is None for e in out[0][1].values())  # tentative: nothing yet
    assert out[1][0].resets == {L, R}
    ids = {(f.slots[L].track_id, f.slots[R].track_id) for f, *_ in out[1:]}
    assert len(ids) == 1
    for frame, evidence, obs, truth in out[1:]:
        assert owner(frame, truth) == {L: "a", R: "b"}
        for h in (L, R):
            assert evidence[h].kind == "MEASURED" and evidence[h].reason == "RED_TIP"
            assert obs[h].method_id is TipMethod.MARKER and obs[h].present
            assert obs[h].tip == evidence[h].tip and obs[h].axis_origin == evidence[h].origin
            assert obs[h].tip_confidence == evidence[h].confidence == 0.9
            assert math.dist((obs[h].tip[0] * 640, obs[h].tip[1] * 480), truth["a" if h is L else "b"]) < 1.0
    assert not any(f.resets for f, *_ in out[2:])


def test_tips_crossing_past_each_other_keep_their_identities():
    a = [(470 - 12 * k, 220) for k in range(30)]
    b = [(130 + 12 * k, 250) for k in range(30)]  # passes 30 px below a
    est, out = track({"a": a, "b": b}, exposure_fraction=0.5)
    assert swapped(out, {L: "a", R: "b"}) == []
    measured = sum(f.slots[h].measured for f, *_ in out[1:] for h in (L, R))
    assert measured == 2 * 29
    assert not any(f.ambiguous for f, *_ in out)


def test_tips_meeting_at_one_point_are_ambiguous_then_restarted_never_swapped():
    a = [(470 - 12 * k, 240) for k in range(30)]
    b = [(130 + 12 * k, 240) for k in range(30)]  # same height: the blobs merge at k = 14
    est, out = track({"a": a, "b": b}, exposure_fraction=0.0)
    assert swapped(out, {L: "a", R: "b"}) == []
    ambiguous = [k for k, (f, *_) in enumerate(out) if f.ambiguous]
    assert ambiguous and all(12 <= k <= 16 for k in ambiguous)
    for k in ambiguous:  # identity not trustworthy: nothing measured, so nothing can strike
        frame, evidence = out[k][0], out[k][1]
        assert not any(frame.slots[h].measured for h in (L, R))
        assert all(e.kind != "MEASURED" for e in evidence.values())
    end = ambiguous[-1] + 1
    assert out[end][0].resets == {L, R}  # the pipeline restarts both hands' strokes
    assert all(owner(f, t) == {L: "a", R: "b"} for f, _, _, t in out[end + 1:])
    assert est.tracker.counters["AMBIGUITY_RESETS"] == 1


def test_fast_alternating_roll_close_together_stays_measured_without_swaps():
    n = 60
    a = [(335.0, 300 + 40 * math.sin(2 * math.pi * 3 * k / 30)) for k in range(n)]  # 3 Hz, 40 px apart
    b = [(295.0, 300 - 40 * math.sin(2 * math.pi * 3 * k / 30)) for k in range(n)]
    est, out = track({"a": a, "b": b}, exposure_fraction=0.5)
    assert swapped(out, {L: "a", R: "b"}) == []
    assert all(f.slots[h].measured for f, *_ in out[1:] for h in (L, R))
    assert not any(f.resets for f, *_ in out[2:])


def test_brief_occlusion_coasts_without_coordinates_and_resumes_the_same_track():
    a = [(320.0, 150.0 + 6 * k) for k in range(24)]
    for k in (10, 11, 12):
        a[k] = None
    est, out = track({"a": a}, exposure_fraction=0.0)
    tid = out[9][0].slots[L].track_id
    for k in (10, 11, 12):
        frame, evidence, obs, _ = out[k]
        st = frame.slots[L]
        assert st.state == "PREDICTED" and st.tip is None and st.track_id == tid
        assert math.dist(st.predicted, (320.0, 150.0 + 6 * k)) < 3  # diagnostics only ...
        assert evidence[L].kind == "UNCERTAIN" and evidence[L].tip is None  # ... never measured
        assert not obs[L].present and obs[L].tip is None
    resumed = out[13][0]
    assert resumed.slots[L].state == "OBSERVED" and resumed.slots[L].track_id == tid and not resumed.resets


def test_prediction_expires_and_a_reappearing_tip_is_tentative_again():
    a = [(320.0, 150.0 + 6 * k) for k in range(30)]
    for k in range(10, 22):  # 0.4 s, longer than max_coast_s (0.25 s)
        a[k] = None
    est, out = track({"a": a}, exposure_fraction=0.0)
    tid = out[9][0].slots[L].track_id
    states = [out[k][0].slots[L].state for k in range(10, 22)]
    assert states[0] == "PREDICTED" and states[-1] == "NO_TRACK"
    assert est.tracker.counters["LOST"] == 1
    assert out[22][1][L].kind == "MISSING"  # the tip is back but a new track is not confirmed yet
    back = out[23][0]
    assert back.slots[L].state == "OBSERVED" and back.slots[L].track_id != tid and L in back.resets


def test_a_red_flash_in_a_single_frame_is_never_measured():
    est, out = track({"a": [None] * 5 + [(400.0, 300.0)] + [None] * 5}, exposure_fraction=0.0)
    assert all(e.kind != "MEASURED" for _, evidence, _, _ in out for e in evidence.values())
    assert est.tracker.counters["TENTATIVE_DROPPED"] == 1


def test_red_objects_that_never_move_yield_their_slots_to_a_moving_tip():
    settings = RedTipSettings(detector="colour", static_window_s=0.5)
    n = 50
    paths = {"s1": [(560.0, 60.0)] * n, "s2": [(80.0, 60.0)] * n,
             "tip": [None] * 20 + [(300.0, 150.0 + 5 * k) for k in range(30)]}
    est, out = track(paths, settings, exposure_fraction=0.0)
    assert owner(out[18][0], out[18][3]) == {L: "s1", R: "s2"}  # the only red things seen so far
    release = next(k for k, (f, *_) in enumerate(out) if k > 20 and f.resets)
    assert owner(out[release][0], out[release][3])[L] == "tip"
    assert all(owner(f, t)[L] == "tip" for f, _, _, t in out[release:])
    assert est.tracker.counters["STATIC_RELEASES"] == 1


def test_a_played_stick_held_still_keeps_its_slot_against_a_moving_red_object():
    settings = RedTipSettings(detector="colour", static_window_s=0.5)
    n = 60
    held = [(450.0, 150.0 + 4 * k) for k in range(10)] + [(450.0, 186.0)] * (n - 10)  # played, then held
    other = [(150.0, 200.0 + 30 * math.sin(k / 3)) for k in range(n)]
    intruder = [None] * 35 + [(560.0, 40.0 + 6 * k) for k in range(n - 35)]
    est, out = track({"held": held, "other": other, "intruder": intruder}, settings, exposure_fraction=0.0)
    assert all(owner(f, t) == {L: "held", R: "other"} for f, _, _, t in out[2:])
    assert est.tracker.counters["STATIC_RELEASES"] == 0


@pytest.mark.parametrize("limit", [1, 3])
def test_blurred_fast_tip_stays_measured_through_weak_redetection_up_to_the_limit(limit):
    ys = [100.0 + 4 * k for k in range(8)]  # slow: strong detections
    for _ in range(6):
        ys.append(ys[-1] + 45)  # fast: the full-exposure streak is too faint for the strong floors
    est, out = track({"a": [(320.0, y) for y in ys]},
                     RedTipSettings(detector="colour", max_weak_frames=limit), exposure_fraction=1.0)
    fast = [out[k][0].slots[L] for k in range(8, 14)]
    assert [s.state for s in fast[:limit]] == ["WEAK"] * limit
    assert all(s.state == "WEAK_LIMIT" for s in fast[limit:])
    for k in range(8, 8 + limit):
        assert out[k][1][L].kind == "MEASURED" and out[k][1][L].reason == "RED_TIP_WEAK"
        assert out[k][2][L].tip_confidence == 0.75
    assert out[8 + limit][1][L].kind == "UNCERTAIN" and not out[8 + limit][2][L].present


def test_a_faint_streak_with_no_track_never_starts_one():
    path = [None, None, (320.0, 300.0), (320.0, 345.0), (320.0, 390.0)]
    est, out = track({"a": path}, exposure_fraction=1.0)
    assert est.tracker.counters["BIRTHS"] <= 1  # only the first, sharp appearance can start a track
    assert all(e.kind != "MEASURED" for _, evidence, _, _ in out for e in evidence.values())


def test_estimate_serves_both_hands_from_one_pass_per_frame():
    est = RedTipEndpointEstimator(RedTipSettings(detector="colour"))
    calls = []
    detect = est.detector.detect
    est.detector.detect = lambda img: calls.append(1) or detect(img)
    frames = path_frames({"a": [(450.0, 200.0)] * 3, "b": [(180.0, 260.0)] * 3}, exposure_fraction=0.0)
    for view, _ in frames:
        hands = [HandObservation.absent(view.sample.frame_id, view.sample.t_capture, h, "x") for h in (L, R)]
        left, right = (est.estimate(view, hand) for hand in hands)
        assert left is est.observations[L] and right is est.observations[R]
    assert len(calls) == 3
    assert left.present and right.present


def test_tracking_is_causal_prefix_invariant():
    a = [(470.0 - 12 * k, 240.0) for k in range(30)]
    b = [(130.0 + 12 * k, 240.0 + (k % 3)) for k in range(30)]
    b[20] = b[21] = None

    def records(n):
        _, out = track({"a": a[:n], "b": b[:n]}, exposure_fraction=0.5)
        return [{**f.to_record(), "ms": None} for f, *_ in out]

    full, prefix = records(30), records(18)
    assert full[:18] == prefix


def test_hand_assist_labels_new_tips_by_grip_and_vetoes_births_far_from_both_hands():
    settings = RedTipSettings(detector="colour", hand_assist=True, hand_reach_spans=5.0)
    a, b = (450.0, 200.0), (180.0, 260.0)  # by camera x alone, a would be LEFT
    grips = {L: np.array([180.0, 330.0]), R: np.array([450.0, 270.0])}  # but the left hand holds b

    def hands(view):
        s = view.sample
        return {h: HandObservation(s.frame_id, s.t_capture, h, True, "synthetic",
                                   tuple(map(tuple, _fist_landmarks(g, 30.0) / (640.0, 480.0))), None, 0.95,
                                   (0, 0, 1, 1)) for h, g in grips.items()}

    paths = {"a": [a] * 6, "b": [b] * 6, "far": [(600.0, 450.0)] * 6}
    est, out = track(paths, settings, hands=hands, exposure_fraction=0.0)
    assert all(owner(f, t) == {L: "b", R: "a"} for f, _, _, t in out[1:])
    assert est.tracker.counters["FAR_FROM_HANDS"] >= 1
    assert all(t["pos"] != (600.0, 450.0) for f, *_ in out for t in f.tracker.tracks)
    obs = out[-1][2][L]
    assert obs.stick_length_est and obs.axis_confidence > 0  # the axis now runs from the grip to the tip


# --- Caps at the owner photo's size (REAL_CAP, ~740 px^2), revision 2026-10-16 ------------------------------


def test_photo_sized_caps_crossing_past_each_other_keep_their_identities():
    a = [(470 - 12 * k, 200) for k in range(30)]
    b = [(130 + 12 * k, 262) for k in range(30)]  # the caps pass ~30 px apart
    est, out = track({"a": a, "b": b}, exposure_fraction=0.5, tip_kw=dict(REAL_CAP))
    assert swapped(out, {L: "a", R: "b"}) == []
    measured = sum(f.slots[h].measured for f, *_ in out[1:] for h in (L, R))
    assert measured >= 0.9 * 2 * 29


def test_no_red_tip_in_view_never_measures_anything():
    est, out = track({"a": [None] * 20}, decorate=lambda img, k: speckles(img, np.random.default_rng(k), 60))
    assert all(f.slots[h].state == "NO_TRACK" for f, *_ in out for h in (L, R))
    assert all(e.kind == "MISSING" and e.tip is None for _, evidence, _, _ in out for e in evidence.values())


def test_small_red_clutter_filling_the_track_table_is_evicted_by_the_real_caps():
    settings = RedTipSettings(detector="colour", max_tracks=4)
    spots = [(60.0, 60.0), (580.0, 60.0), (60.0, 420.0), (580.0, 420.0)]

    def clutter(img, k):
        for p in spots:
            draw_blob(img, p, 6.0, hue=178, sat=220, val=190)  # same paint, ~120 px^2: a low score

    n = 30
    a = [None] * 8 + [(430.0, 150.0 + 6 * k) for k in range(n - 8)]
    b = [None] * 8 + [(210.0, 300.0 - 5 * k) for k in range(n - 8)]
    est, out = track({"a": a, "b": b}, settings, exposure_fraction=0.0, decorate=clutter,
                     tip_kw=dict(REAL_CAP))
    assert est.tracker.counters["TRACK_EVICTED"] >= 2
    for frame, _, _, truth in out:  # no slot is ever measured on the clutter
        assert None not in owner(frame, truth).values()
    assert owner(out[-1][0], out[-1][3]) == {L: "a", R: "b"}


def test_a_static_red_object_never_takes_a_slot_from_sticks_held_still_and_moving_caps_bind():
    n = 30
    lamp = [(590.0, 50.0)] * n  # the same paint, larger than nothing in particular: indistinguishable at rest
    a = [(430.0, 200.0)] * 10 + [(430.0, 200.0 + 7 * k) for k in range(n - 10)]
    b = [(210.0, 240.0)] * 10 + [(210.0, 240.0 + 6 * k) for k in range(n - 10)]
    est, out = track({"lamp": lamp, "a": a, "b": b}, exposure_fraction=0.0, tip_kw=dict(REAL_CAP))
    assert all(not f.slots[h].measured for f, *_ in out[:10] for h in (L, R))  # three candidates: no guess
    assert est.tracker.counters["BIND_DEFERRED"] >= 8
    bound = [k for k, (f, *_) in enumerate(out) if all(f.slots[h].measured for h in (L, R))]
    assert bound and bound[0] <= 16  # bound within a few frames of moving
    assert all(owner(f, t) == {L: "a", R: "b"} for f, _, _, t in out[bound[0]:])


def test_a_tracked_stroke_that_speeds_up_stays_measured_on_its_saturated_core():
    ys = [150.0 + 4 * k for k in range(10)] + [190.0 + 44 * k for k in range(1, 6)]  # then 44 px per frame
    est, out = track({"a": [(420.0, y) for y in ys]}, exposure_fraction=1.0, tip_kw=dict(REAL_CAP))  # LEFT
    fast = [out[k][0].slots[L] for k in range(10, 15)]
    assert all(st.state == "OBSERVED" for st in fast)  # strong evidence, not the limited weak class
    assert est.tracker.counters["CORE_FRAMES"] >= 1
    assert all(abs(st.tip[1] - (y - 22)) < 6 for st, y in zip(fast, ys[10:], strict=True))  # mid-exposure


def test_a_blurred_core_alone_never_starts_a_track():
    def streak(img, k):
        draw_tip(img, (300.0, 100.0 + 44 * k), blur_from=(300.0, 56.0 + 44 * k), **REAL_CAP)

    est, out = track({"a": [None] * 8}, decorate=streak)
    assert all(not f.slots[h].measured for f, *_ in out for h in (L, R))
    assert est.tracker.counters["BIRTHS"] == 0


def test_a_blob_touching_the_frame_border_never_takes_a_free_slot():
    """Live session 2026-10-16 225536: both slots sat on blobs at the bottom edge (hands, sofa) for most of
    the session; a clipped blob is never measured, so binding it only blocks the slot."""
    n = 20
    edge = [(600.0, 476.0)] * n  # a red thing cut by the bottom of the frame
    tip = [(430.0, 150.0 + 6 * k) for k in range(n)]
    est, out = track({"edge": edge, "tip": tip}, exposure_fraction=0.0, tip_kw=dict(REAL_CAP))
    assert all(owner(f, t).get(L) in (None, "tip") and owner(f, t).get(R) is None for f, _, _, t in out)
    assert all(f.slots[R].state == "NO_TRACK" for f, *_ in out)  # the edge blob alone is not a stick
    assert owner(out[-1][0], out[-1][3]) == {L: "tip"}
