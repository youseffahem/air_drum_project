"""TEST-CAUSAL-1 and TEST-CAUSAL-2 for the rule-based ``Anticipator`` (causality-tests.md sections 2-3).

Inputs are SYNTHETIC observation sequences (tests/tracking/conftest helpers re-used through the
tracker so the anticipator sees real ``TrackState`` histories). Outputs are compared as canonical
JSON; ``t_inference_done`` is a wall-clock stamp and is pinned by an injected clock so that
"bit-identical" is meaningful for the decision fields.
"""

from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path

import pytest

from spacedrums.config import canonical_json
from spacedrums.contracts import HandId, ResetReason
from spacedrums.prediction import RuleBasedAnticipator, RuleSettings
from spacedrums.tracking import CausalTracker, StateMachineSettings, TrackerSettings


def _load_tracking_helpers():
    """The SYNTHETIC observation helpers of tests/tracking/conftest.py under a non-colliding module name."""
    path = Path(__file__).resolve().parents[1] / "tracking" / "conftest.py"
    spec = importlib.util.spec_from_file_location("tracking_synthetic_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_H = _load_tracking_helpers()
DT, hand_obs, make_sequence, stick_obs = _H.DT, _H.hand_obs, _H.make_sequence, _H.stick_obs

MACHINE = StateMachineSettings(c_valid=0.6, c_min=0.3, g_max_frames=3, age_max_s=0.5)


def _curved_truth(n: int):
    """A curving stroke (direction changes every frame) so the direction gate has real memory."""
    return [
        (0.2 + 0.5 * k * DT + 0.8 * (k * DT) ** 2, 0.2 + 0.2 * math.sin(2.5 * k * DT) + 1.5 * (k * DT) ** 2)
        for k in range(n)
    ]


def _tracker() -> CausalTracker:
    tr = CausalTracker(HandId.RIGHT, TrackerSettings(filter_type="kalman_cv", machine=MACHINE, history_n=16))
    tr.reset(ResetReason.SESSION_START)
    return tr


def _anticipator(model: str = "CV") -> RuleBasedAnticipator:
    return RuleBasedAnticipator(
        RuleSettings(
            anticipator_id="rule-causal",
            motion_model=model,
            K=6,
            dt_step=DT,
            v_min_predict=0.0,
            direction_window_frames=3,
        ),
        clock=lambda: 0.0,
    )


def _run(seq, model: str = "CV") -> list[dict | None]:
    tr, ant = _tracker(), _anticipator(model)
    out = []
    for t, h, s in seq:
        tr.update(h, s, t)
        pred = ant.predict(tr.history)
        out.append(pred.to_dict() if pred is not None else None)
    return out


def _canon(d) -> bytes:
    return canonical_json(d)


def _garbage(seq, start: int, seed: int = 0):
    rng = random.Random(seed)
    out = list(seq[: start + 1])
    for t, h, _s in seq[start + 1 :]:
        present = rng.random() < 0.7
        tip = (rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2)) if present else None
        out.append(
            (t, hand_obs(h.frame_id, t, present=present), stick_obs(h.frame_id, t, tip, rng.uniform(0, 1)))
        )
    return out


def _shifted(seq, other, start: int):
    out = list(seq[: start + 1])
    for (t, h, _s), (_t2, _h2, s2) in zip(seq[start + 1 :], other[start + 1 :], strict=False):
        s_new = (
            stick_obs(h.frame_id, t, s2.tip, s2.tip_confidence, axis_dir=s2.axis_dir)
            if s2.present
            else stick_obs(h.frame_id, t, None, 0.0)
        )
        out.append((t, h, s_new))
    return out


@pytest.mark.parametrize("model", ["CV", "CA"])
def test_causal_1_future_perturbation_invariance_synthetic(model, capsys):
    base = make_sequence(
        _curved_truth(80),
        noise=0.003,
        seed=3,
        jitter_dt=0.003,
        gaps={30, 31, 32, 33, 34},
        low_conf={12: 0.4, 50: 0.2},
    )
    other = make_sequence([(0.8 - 0.3 * k * DT, 0.9 - 0.4 * k * DT) for k in range(80)], noise=0.003, seed=9)
    ref = _run(base, model)
    cuts = sorted(
        {
            c
            for c in list(range(9, len(base), 10)) + [i for i, p in enumerate(ref) if p is None]
            if c < len(base) - 1
        }
    )
    failures = []
    for i in cuts:
        for kind, seq in (
            ("GARBAGE", _garbage(base, i)),
            ("REMOVED", base[: i + 1]),
            ("SHIFTED", _shifted(base, other, i)),
        ):
            got = _run(seq, model)
            failures += [(i, kind, k) for k in range(i + 1) if _canon(got[k]) != _canon(ref[k])]
    with capsys.disabled():
        print(
            f"\nTEST-CAUSAL-1 rule-based[{model}] SYNTHETIC: |I|={len(cuts)} "
            f"kinds=GARBAGE,REMOVED,SHIFTED -> "
            f"{'PASS' if not failures else 'FAIL'} ({len(failures)} differing tuples)"
        )
    assert not failures, failures[:10]


def test_causal_1_adversarial_future_mutation_after_prediction():
    """Mutating or appending future TrackStates after a prediction never changes that prediction."""
    tr, ant = _tracker(), _anticipator("CA")
    seq = make_sequence(_curved_truth(30), noise=0.002, seed=1)
    for t, h, s in seq[:20]:
        tr.update(h, s, t)
    history = list(tr.history)
    before = ant.predict(history).to_dict()
    # 1. append garbage "future" states to a copy of the history used for the prediction: the call
    #    only ever sees the prefix, so we assert on the prefix explicitly and on the full list too
    for t, h, s in seq[20:]:
        tr.update(h, s, t)
    future = [st for st in tr.history if st.t_capture > history[-1].t_capture]
    assert future, "sequence must extend past the prediction time"
    assert ant.predict(history).to_dict() == before
    # 2. the prediction from the longer history at a later time is a different object with a later t_ref
    later = ant.predict(tr.history)
    assert later.t_capture > before["t_capture"]
    # 3. a prediction made at the same t_ref from the same prefix, after the future has been seen by the
    #    tracker, is identical: the anticipator holds no state that the future could have altered
    assert ant.predict(history).to_dict() == before


@pytest.mark.parametrize("model", ["CV", "CA"])
def test_causal_2_history_truncation_with_declared_window(model, capsys):
    base = make_sequence(_curved_truth(120), noise=0.003, seed=5)
    tr, ant = _tracker(), _anticipator(model)
    decl = ant.declared_history()
    n, n_min = decl["N"], decl["N_min"]
    histories, ref = [], []
    for t, h, s in base:
        tr.update(h, s, t)
        histories.append(list(tr.history))
        pred = ant.predict(tr.history)
        ref.append(pred.to_dict() if pred is not None else None)
    cuts = [i for i in range(n + n_min, len(base), 5) if ref[i] is not None and len(histories[i]) > n]
    assert cuts
    diffs = [
        i for i in cuts if _canon(_anticipator(model).predict(histories[i][-n:]).to_dict()) != _canon(ref[i])
    ]
    # negative control: a window of N - 1 states must change the output (direction gate / finite difference)
    neg = sum(
        1
        for i in cuts
        if _canon(_anticipator(model).predict(histories[i][-(n - 1) :]).to_dict()) != _canon(ref[i])
    )
    with capsys.disabled():
        print(
            f"\nTEST-CAUSAL-2 rule-based[{model}] SYNTHETIC: N={n} N_min={n_min} |I|={len(cuts)} -> "
            f"{'PASS' if not diffs else 'FAIL'}; negative control (window {n - 1}) differs in "
            f"{neg}/{len(cuts)} cuts "
            f"{'(ok)' if neg else 'DOES NOT DIFFER'}"
        )
    assert not diffs, diffs[:10]
    assert neg > 0
