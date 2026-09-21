"""TEST-CONFORM-2 (Tracker) + TEST-TRACK-3: CausalTracker on SYNTHETIC sequences (Phase 03, Task 03.13).

Includes the induced-occlusion trace: the hand vanishes for a controlled interval; the trace must
show DEGRADED bridging for <= g_max frames, then INVALID with a reset, never a fabricated VALID.
"""

from __future__ import annotations

import pytest
from conftest import DT, constant_velocity_truth, make_sequence

from spacedrums.contracts import HandId, ResetReason, TipMethod, Tracker, TrackStatus
from spacedrums.contracts import schema as contract_schema
from spacedrums.tracking import FILTER_TYPES, CausalTracker, StateMachineSettings, TrackerSettings

MACHINE = StateMachineSettings(c_valid=0.6, c_min=0.3, g_max_frames=3, age_max_s=0.5)


def _tracker(ftype="kalman_cv", hand=HandId.RIGHT, n=16) -> CausalTracker:
    return CausalTracker(hand, TrackerSettings(filter_type=ftype, machine=MACHINE, history_n=n,
                                               roi_aspect=560 / 440))


def _run(tr, seq):
    return [tr.update(h, s, t) for t, h, s in seq]


@pytest.mark.parametrize("ftype", FILTER_TYPES)
def test_conform_2_schema_valid_states_monotone_time(ftype, cv_sequence):
    tr = _tracker(ftype)
    assert isinstance(tr, Tracker)
    states = _run(tr, cv_sequence)
    assert len(states) == len(cv_sequence)
    for st in states:
        errs = contract_schema.errors("track-state", st.to_dict())
        assert not errs, errs
    ts = [st.t_capture for st in states]
    assert all(b >= a for a, b in zip(ts, ts[1:], strict=False))
    assert states[0].status is TrackStatus.VALID and states[0].history_ref.n == 0
    assert states[-1].status is TrackStatus.VALID and states[-1].tip_method is TipMethod.GEOM
    assert states[-1].tip_velocity[0] == pytest.approx(0.3, abs=0.1)
    assert states[-1].axis_angle is not None and states[-1].axis_angular_velocity is not None


def test_conform_2_history_window_bounded_causal_oldest_first(cv_sequence):
    tr = _tracker(n=8)
    for k, (t, h, s) in enumerate(cv_sequence):
        st = tr.update(h, s, t)
        hist = tr.history
        assert len(hist) <= 8
        assert all(x.t_capture <= t for x in hist)
        assert [x.frame_id for x in hist] == sorted(x.frame_id for x in hist)
        if k >= 8:
            assert st.history_ref.n == 8 and st.history_ref.oldest_frame_id == k - 8


def test_conform_2_present_false_never_raises_and_gives_invalid():
    tr = _tracker()
    seq = make_sequence(constant_velocity_truth(5), gaps={0, 1, 2, 3, 4})
    states = _run(tr, seq)
    assert all(st.status is TrackStatus.INVALID for st in states)
    assert all(st.tip_filtered is None and st.tip_velocity is None and st.tip_acceleration is None
               for st in states)
    assert all(st.confidence == 0.0 and st.history_ref is None for st in states)
    assert tr.resets == []  # nothing to reset from


def test_conform_2_transitions_valid_degraded_invalid_stale_reacquire():
    tr = _tracker()
    truth = constant_velocity_truth(70)
    low = {5: 0.4, 6: 0.35}
    gaps = set(range(10, 40))  # 30-frame occlusion (1.0 s) > age_max 0.5 s
    seq = make_sequence(truth, gaps=gaps, low_conf=low)
    states = _run(tr, seq)
    status = [st.status for st in states]
    assert status[:5] == [TrackStatus.VALID] * 5
    assert status[5:7] == [TrackStatus.DEGRADED] * 2 and states[5].tip_filtered is not None
    assert status[7:10] == [TrackStatus.VALID] * 3
    assert status[10:13] == [TrackStatus.DEGRADED] * 3  # g_max = 3 bridged frames, prediction only
    assert states[13].status is TrackStatus.INVALID and states[13].reset_reason is ResetReason.GAP_EXCEEDED
    # bridged states carry positions (existing state propagated) with decaying confidence
    assert states[10].tip_filtered is not None and states[12].confidence < states[10].confidence
    # STALE appears once t - last_valid_t > age_max (0.5 s = 15 frames after frame 9)
    stale_idx = next(i for i, s in enumerate(status) if s is TrackStatus.STALE)
    assert 24 <= stale_idx <= 26 and states[stale_idx].reset_reason is ResetReason.STALE
    assert all(s is TrackStatus.STALE for s in status[stale_idx:40])
    assert status[40] is TrackStatus.VALID and states[40].frames_since_valid == 0  # re-acquired
    assert states[40].history_ref.n == 0  # history restarted after the loss
    reasons = [r.reason for r in tr.resets]
    assert reasons == [ResetReason.GAP_EXCEEDED, ResetReason.STALE]
    # never a fabricated VALID inside the occlusion
    assert all(s is not TrackStatus.VALID for s in status[10:40])


def test_conform_2_reset_clears_history_and_sets_reason():
    tr = _tracker()
    seq = make_sequence(constant_velocity_truth(10))
    _run(tr, seq[:6])
    assert len(tr.history) == 6
    tr.reset(ResetReason.MANUAL)
    assert len(tr.history) == 0
    st = tr.update(seq[6][1], seq[6][2], seq[6][0])
    assert st.reset_reason is ResetReason.MANUAL and st.status is TrackStatus.VALID and st.history_ref.n == 0
    assert tr.resets[-1].reason is ResetReason.MANUAL


def test_per_hand_independence_and_wrong_hand_rejected():
    left, right = _tracker(hand=HandId.LEFT), _tracker(hand=HandId.RIGHT)
    seq_r = make_sequence(constant_velocity_truth(10))
    seq_l = make_sequence(constant_velocity_truth(10), gaps=set(range(10)), hand=HandId.LEFT)
    for (t, h, s), (_, hl, sl) in zip(seq_r, seq_l, strict=True):
        right.update(h, s, t)
        left.update(hl, sl, t)
    assert right.history and not left.history  # LEFT saw nothing, RIGHT tracked: no coupling
    with pytest.raises(ValueError):
        right.update(seq_l[0][1], seq_l[0][2], seq_l[0][0])


def test_out_of_order_frames_rejected():
    tr = _tracker()
    seq = make_sequence(constant_velocity_truth(3))
    tr.update(seq[1][1], seq[1][2], seq[1][0])
    with pytest.raises(ValueError):
        tr.update(seq[0][1], seq[0][2], seq[0][0])


def test_tracker_id_pins_filter_and_thresholds():
    tr = CausalTracker("LEFT", TrackerSettings(filter_type="alpha_beta",
                                               filter_params={"alpha": 0.5, "beta": 0.2},
                                               machine=MACHINE, history_n=12))
    assert tr.tracker_id == "causal-tracker:alpha_beta:alpha0.5-beta0.2:cv0.60:cm0.30:g3:age0.50:N12"
    d = tr.declared_history()
    assert d["N"] == 12 and d["N_eff"] >= 1 and d["tolerance"] == 1e-6


def test_from_config_reads_the_tracking_block():
    cfg = {"roi": {"px": [40, 20, 560, 440]},
           "tracking": {"tracker_id": "t", "c_valid": 0.6, "c_min": 0.3, "g_max_frames": 3, "age_max_s": 0.5,
                        "history_n": 16,
                        "filter": {"type": "kalman_ca", "params": {"q": 2.0, "bridge_decay": 0.8}}}}
    s = TrackerSettings.from_config(cfg)
    assert s.filter_type == "kalman_ca" and s.filter_params["q"] == 2.0 and s.machine.bridge_decay == 0.8
    assert s.roi_aspect == pytest.approx(560 / 440)


def test_induced_occlusion_trace_is_printed(capsys):
    """State trace of a controlled occlusion (SYNTHETIC; the dev-capture trace is in the benchmark run)."""
    tr = _tracker()
    seq = make_sequence(constant_velocity_truth(24), gaps=set(range(8, 16)))
    states = _run(tr, seq)
    trace = " ".join(st.status.value[0] for st in states)  # V D I S
    with capsys.disabled():
        print(f"\nSYNTHETIC occlusion trace (frames 8-15 absent, g_max 3): {trace}")
        print("  resets:", [(r.frame_id, str(r.reason)) for r in tr.resets])
    assert trace.split()[8:11] == ["D", "D", "D"] and trace.split()[11] == "I"
    assert trace.split()[16] == "V"
    assert DT > 0
