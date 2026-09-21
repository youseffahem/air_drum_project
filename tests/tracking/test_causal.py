"""TEST-CAUSAL-1 and TEST-CAUSAL-2 for the ``Tracker`` (docs/architecture/causality-tests.md sections 2-3).

Sequences: SYNTHETIC (conftest; labelled synthetic) and, when the developer capture is on this
machine, the recorded ``swing-L2-exp-5`` run through the real hands + stick pipeline (the same
observations the benchmark script logs). The tests print the evidence lines the gate record cites.

TEST-CAUSAL-2 note: none of the filters has a hard window; each declares ``N_eff`` at the declared
tolerance (``TrackerSettings.causal_tolerance``, 1e-6 ROI-normalized). The test measures the actual
deviation of a cold start on the last ``N_eff`` frames and fails if it exceeds the tolerance (the
declaration would be wrong). Non-numeric fields (status, tip_method) must be identical; the
``history_ref`` window metadata is excluded (it describes the window itself).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest
from conftest import constant_velocity_truth, hand_obs, make_sequence, parabolic_truth, stick_obs

from spacedrums.config import canonical_json
from spacedrums.contracts import HandId, ResetReason, TrackState, TrackStatus
from spacedrums.tracking import FILTER_TYPES, CausalTracker, StateMachineSettings, TrackerSettings

ROOT = Path(__file__).resolve().parents[2]
DEV_CAPTURE = ROOT / "data" / "dev-captures" / "swing-L2-exp-5"
MODEL = ROOT / "assets" / "models" / "hand_landmarker.task"
MACHINE = StateMachineSettings(c_valid=0.6, c_min=0.3, g_max_frames=3, age_max_s=0.5)
KINEMATIC = ("tip_filtered", "tip_velocity", "tip_acceleration", "axis_angle", "axis_angular_velocity")


def _tracker(ftype: str, n: int = 16) -> CausalTracker:
    tr = CausalTracker(HandId.RIGHT, TrackerSettings(filter_type=ftype, machine=MACHINE, history_n=n,
                                                     roi_aspect=560 / 440))
    tr.reset(ResetReason.SESSION_START)
    return tr


def _run(tr: CausalTracker, seq) -> list[dict]:
    return [tr.update(h, s, t).to_dict() for t, h, s in seq]


def _canon(d: dict) -> bytes:
    return canonical_json(d)


def _garbage(seq, start: int, seed: int = 0):
    """Frames > start replaced by schema-valid random records (GARBAGE perturbation)."""
    rng = random.Random(seed)
    out = list(seq[: start + 1])
    for t, h, _s in seq[start + 1:]:
        present = rng.random() < 0.7
        tip = (rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2)) if present else None
        out.append((t, hand_obs(h.frame_id, t, present=present),
                    stick_obs(h.frame_id, t, tip, rng.uniform(0, 1))))
    return out


def _shifted(seq, other, start: int):
    out = list(seq[: start + 1])
    for (t, h, _s), (_t2, _h2, s2) in zip(seq[start + 1:], other[start + 1:], strict=False):
        s_new = stick_obs(h.frame_id, t, s2.tip, s2.tip_confidence, axis_dir=s2.axis_dir) if s2.present \
            else stick_obs(h.frame_id, t, None, 0.0)
        out.append((t, h, s_new))
    return out


def _synthetic_sequences():
    base = make_sequence(constant_velocity_truth(80), noise=0.004, seed=1, jitter_dt=0.004,
                         gaps={30, 31, 32, 33, 34, 35}, low_conf={12: 0.4, 13: 0.2, 50: 0.45})
    other = make_sequence(parabolic_truth(80), noise=0.004, seed=7)
    return base, other


@pytest.mark.parametrize("ftype", FILTER_TYPES)
def test_causal_1_future_perturbation_invariance_synthetic(ftype, capsys):
    base, other = _synthetic_sequences()
    ref = _run(_tracker(ftype), base)
    cuts = list(range(9, len(base), 10)) + [i for i, st in enumerate(ref) if st["reset_reason"]]
    cuts = sorted(set(c for c in cuts if c < len(base) - 1))
    failures = []
    for i in cuts:
        variants = (("GARBAGE", _garbage(base, i)), ("REMOVED", base[: i + 1]),
                    ("SHIFTED", _shifted(base, other, i)))
        for kind, seq in variants:
            got = _run(_tracker(ftype), seq)
            for k in range(i + 1):
                if _canon(got[k]) != _canon(ref[k]):
                    failures.append((i, kind, k))
    with capsys.disabled():
        print(f"\nTEST-CAUSAL-1 tracker[{ftype}] SYNTHETIC: |I|={len(cuts)} kinds=GARBAGE,REMOVED,SHIFTED "
              f"-> {'PASS' if not failures else 'FAIL'} ({len(failures)} differing tuples)")
    assert not failures, failures[:10]


DT_NOMINAL = 1 / 30
# position-equivalent scaling of the kinematic fields: the tolerance is stated in ROI-normalized
# position units (causality-tests.md 2, candidate 1e-6), so velocities are compared x dt and
# accelerations x dt^2 (what they contribute to the next position); angles in radians, omega x dt.
SCALE = {"tip_filtered": 1.0, "tip_velocity": DT_NOMINAL, "tip_acceleration": DT_NOMINAL**2,
         "axis_angle": 1.0, "axis_angular_velocity": DT_NOMINAL}


def _deviation(a: dict, b: dict) -> float:
    worst = 0.0
    for f in KINEMATIC:
        va, vb = a[f], b[f]
        if va is None or vb is None:
            if va != vb:
                return math.inf
            continue
        if isinstance(va, list):
            worst = max(worst, SCALE[f] * max(abs(x - y) for x, y in zip(va, vb, strict=True)))
        else:
            worst = max(worst, SCALE[f] * abs(va - vb))
    return worst


@pytest.mark.parametrize("ftype", FILTER_TYPES)
def test_causal_2_history_truncation_with_declared_n_eff_synthetic(ftype, capsys):
    # a long uninterrupted VALID run (the declaration concerns the filter memory; a gap resets the state)
    base = make_sequence(parabolic_truth(400, a=(0.3, 0.8), v0=(0.05, -0.1), p0=(0.3, 0.6)), noise=0.004,
                         seed=5, jitter_dt=0.003)
    tr_ref = _tracker(ftype)
    ref = _run(tr_ref, base)
    decl = tr_ref.declared_history(dt=1 / 30)
    n_eff, tol = decl["N_eff"], decl["tolerance"]
    n_win = max(n_eff, decl["N"])

    def truncated_output(window: int, i: int) -> dict:
        tr = _tracker(ftype)
        return _run(tr, base[i - window + 1: i + 1])[-1]

    # cuts: frames well inside a VALID run (the declaration is about the filter memory, not about
    # re-acquisition, which resets the state anyway)
    valid_run = [i for i, st in enumerate(ref) if st["status"] == "VALID"
                 and all(ref[j]["status"] == "VALID" for j in range(max(0, i - n_win), i))]
    cuts = [i for i in valid_run if i >= n_win + decl["N_min"] and i % 5 == 0]
    assert cuts, "sequence too short for the declared window"
    worst = 0.0
    for i in cuts:
        out = truncated_output(n_win, i)
        assert out["status"] == ref[i]["status"] and out["tip_method"] == ref[i]["tip_method"]
        assert out["frames_since_valid"] == ref[i]["frames_since_valid"]
        assert out["confidence"] == ref[i]["confidence"]
        # history_ref is metadata about the window itself (a cold start on N frames holds N-1 past
        # states where the steady run holds N): excluded from the comparison by definition.
        worst = max(worst, _deviation(out, ref[i]))
    # negative control: a window of 2 frames must not reproduce the reference (memory is detectable)
    neg = max(_deviation(truncated_output(2, i), ref[i]) for i in cuts)
    with capsys.disabled():
        print(f"\nTEST-CAUSAL-2 tracker[{ftype}] SYNTHETIC: N={decl['N']} N_eff={n_eff} window={n_win} "
              f"N_min={decl['N_min']} |I|={len(cuts)} tolerance={tol:g} max_dev={worst:.2e} "
              f"-> {'PASS' if worst <= tol else 'FAIL'}; negative control (window 2) max_dev={neg:.2e} "
              f"{'differs (ok)' if neg > tol else 'DOES NOT DIFFER'}")
    assert worst <= tol, f"declared N_eff {n_eff} too small: max deviation {worst:.3e} > {tol}"
    assert neg > tol


@pytest.mark.skipif(not (MODEL.exists() and (DEV_CAPTURE / "frames.jsonl").exists()),
                    reason="model or developer capture swing-L2-exp-5 not on this machine")
def test_causal_1_and_2_on_recorded_dev_capture(capsys):
    """Recorded observations (hands + stick GEOM on exp-5, all frames) through the default tracker."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from _devcapture import iter_views, load_dev_capture

    from spacedrums.config import load_config
    from spacedrums.hands import HandLandmarker, HandLandmarkerSettings
    from spacedrums.stick import GeomTipEstimator, StickSettings

    cfg = load_config(ROOT / "configs" / "example.candidate.yaml",
                      ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml")
    cap = load_dev_capture("swing-L2-exp-5")
    seq = []
    with HandLandmarker(HandLandmarkerSettings.from_config(cfg.data)) as lm:
        est = GeomTipEstimator(StickSettings.from_config(cfg.data))
        for view in iter_views(cap):
            res = lm.detect(view)
            h = res.right
            seq.append((view.sample.t_capture, h, est.estimate(view, h)))
    settings = TrackerSettings.from_config(cfg.data)

    def tracker():
        tr = CausalTracker(HandId.RIGHT, settings)
        tr.reset(ResetReason.SESSION_START)
        return tr

    ref = _run(tracker(), seq)
    n_valid = sum(1 for s in ref if s["status"] == "VALID")
    cuts = [i for i in range(9, len(seq) - 1, 10)]
    fails = []
    for i in cuts:
        for kind, s2 in (("GARBAGE", _garbage(seq, i)), ("REMOVED", seq[: i + 1])):
            got = _run(tracker(), s2)
            fails += [(i, kind, k) for k in range(i + 1) if _canon(got[k]) != _canon(ref[k])]
    decl = tracker().declared_history()
    n_win = max(decl["N_eff"], decl["N"])
    c2 = [i for i in range(n_win + 1, len(seq))
          if all(ref[j]["status"] == "VALID" for j in range(i - n_win, i + 1))]
    worst = max((_deviation(_run(tracker(), seq[i - n_win + 1: i + 1])[-1], ref[i]) for i in c2),
                default=0.0)
    with capsys.disabled():
        print(f"\nTEST-CAUSAL-1 tracker[{settings.filter_type}] dev capture swing-L2-exp-5 "
              f"({len(seq)} frames, RIGHT, {n_valid} VALID): |I|={len(cuts)} kinds=GARBAGE,REMOVED -> "
              f"{'PASS' if not fails else 'FAIL'}")
        verdict = ("NOT EXERCISED (no uninterrupted VALID run >= window in this capture)" if not c2
                   else ("PASS" if worst <= decl["tolerance"] else "FAIL"))
        print(f"TEST-CAUSAL-2 tracker[{settings.filter_type}] dev capture: window={n_win} |I|={len(c2)} "
              f"max_dev={worst:.2e} tolerance={decl['tolerance']:g} -> {verdict}")
    assert not fails
    assert worst <= decl["tolerance"]
    assert all(TrackState.from_dict(s).status in TrackStatus for s in ref)
    assert json.dumps(ref[0])  # serialisable
