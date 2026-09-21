"""TEST-CAUSAL-1 / TEST-CAUSAL-2 for the ``CommitPolicy`` (causality-tests.md; Phase 05 row).

The component's input is the per-frame stream ``(candidates, TrackState, t_now)``; outputs are the
``CommittedStrike`` lists. SYNTHETIC streams from a seeded generator.
"""

from __future__ import annotations

import math
import random

from commit_helpers import candidate, policy, track

from spacedrums.config import canonical_json
from spacedrums.contracts import TrackStatus


def _stream(seed: int, n: int = 240):
    rng = random.Random(seed)
    t = 1.0
    out = []
    for frame in range(n):
        t += 1 / 30
        status = rng.choice(list(TrackStatus)) if rng.random() < 0.2 else TrackStatus.VALID
        pos = (0.5, rng.uniform(0.3, 0.9))
        cands = [
            candidate(
                frame,
                t,
                zone_id=rng.choice(["snare", "tom1"]),
                t_impact=t + rng.uniform(-0.05, 0.15),
                prob=rng.random(),
                cid=f"s{seed}-f{frame}-{k}",
            )
            for k in range(rng.choice([0, 1, 1, 2]))
        ]
        out.append((cands, track(frame, t, status=status, pos=pos), t, rng.choice([0, 0, 0, 2])))
    return out


def _run(stream, registry, **kw):
    p = policy(registry, refractory_zone_s=0.1, refractory_hand_s=0.04, tti_commit_s=0.1, p_commit=0.3, **kw)
    return [
        [c.to_dict() for c in p.step(cands, ts, t_now, dropped_since_last=drop)]
        for cands, ts, t_now, drop in stream
    ]


def _garbage(stream, i, seed):
    rng = random.Random(seed)
    out = list(stream[: i + 1])
    for _cands, ts, t_now, _drop in stream[i + 1 :]:
        fake = [
            candidate(
                ts.frame_id,
                ts.t_capture,
                zone_id=rng.choice(["snare", "tom1", "kick"]),
                t_impact=t_now + rng.uniform(-1, 1),
                prob=rng.random(),
                cid=f"g{ts.frame_id}-{k}",
            )
            for k in range(rng.choice([0, 1, 3]))
        ]
        st = rng.choice(list(TrackStatus))
        out.append(
            (
                fake,
                track(ts.frame_id, ts.t_capture, status=st, pos=(rng.random(), rng.random())),
                t_now,
                rng.choice([0, 5]),
            )
        )
    return out


def test_causal_1_commit_policy_future_perturbation_invariance(registry, capsys):
    base = _stream(seed=7)
    ref = _run(base, registry)
    cuts = sorted(
        {c for c in list(range(9, len(base), 10)) + [i for i, o in enumerate(ref) if o] if c < len(base) - 1}
    )
    failures = []
    for i in cuts:
        for kind, s in (
            ("GARBAGE", _garbage(base, i, seed=i)),
            ("REMOVED", base[: i + 1]),
            ("SHIFTED", base[: i + 1] + _stream(seed=99)[i + 1 :]),
        ):
            got = _run(s, registry)
            failures += [
                (i, kind, k) for k in range(i + 1) if canonical_json(got[k]) != canonical_json(ref[k])
            ]
    with capsys.disabled():
        print(
            f"\nTEST-CAUSAL-1 commit-policy SYNTHETIC: |I|={len(cuts)} kinds=GARBAGE,REMOVED,SHIFTED -> "
            f"{'PASS' if not failures else 'FAIL'} ({len(failures)} differing tuples); "
            f"{sum(len(o) for o in ref)} commits in the reference run"
        )
    assert not failures, failures[:10]


def test_causal_2_commit_policy_declared_effective_window(registry, capsys):
    """The policy's memory is time-bounded: refractory (r_zone, r_hand), the ARMED counter and an open
    episode. With no open episode at the cut, a cold start N_eff frames before the cut reproduces the
    decision at the cut. N_eff = ceil((max(r_zone, r_hand) + stale_tolerance) / dt) + n_confirm + 1;
    open episodes (tip inside a zone after a commit) are the stated limitation and are excluded."""
    base = _stream(seed=11, n=400)
    dt = 1 / 30
    r_zone, r_hand, stale, n_confirm = 0.1, 0.04, 0.02, 2
    n_eff = math.ceil((max(r_zone, r_hand) + stale) / dt) + n_confirm + 1
    p = policy(
        registry,
        refractory_zone_s=r_zone,
        refractory_hand_s=r_hand,
        tti_commit_s=0.1,
        p_commit=0.3,
        n_confirm_frames=n_confirm,
        stale_prediction_tolerance_s=stale,
    )
    ref, blocked = [], []
    for cands, ts, t_now, drop in base:
        ref.append([c.to_dict() for c in p.step(cands, ts, t_now, dropped_since_last=drop)])
        blocked.append(any(m.episode_blocked() for m in p.machines.values()))
    # cuts: frames that received candidates (commit or gate rejection) with no open episode in the window
    cuts = [i for i in range(n_eff + 1, len(base), 3) if base[i][0] and not any(blocked[i - n_eff : i])]
    assert cuts and any(ref[i] for i in cuts), (
        "need cuts with candidates (some committing) and no open episode"
    )
    diffs, neg = [], 0
    for i in cuts:

        def cold(window: int, i: int = i) -> list:
            q = policy(
                registry,
                refractory_zone_s=r_zone,
                refractory_hand_s=r_hand,
                tti_commit_s=0.1,
                p_commit=0.3,
                n_confirm_frames=n_confirm,
                stale_prediction_tolerance_s=stale,
            )
            out = None
            for cands, ts, t_now, drop in base[i - window + 1 : i + 1]:
                out = [
                    {**c.to_dict(), "strike_id": None, "episode_id": None}
                    for c in q.step(cands, ts, t_now, dropped_since_last=drop)
                ]
            return out

        target = [
            {**c, "strike_id": None, "episode_id": None} for c in ref[i]
        ]  # counters are session-scoped ids
        if canonical_json(cold(n_eff)) != canonical_json(target):
            diffs.append(i)
        if canonical_json(cold(1)) != canonical_json(target):
            neg += 1
    with capsys.disabled():
        print(
            f"\nTEST-CAUSAL-2 commit-policy SYNTHETIC: N_eff={n_eff} frames |I|={len(cuts)} -> "
            f"{'PASS' if not diffs else 'FAIL'}; negative control (window 1) differs in "
            f"{neg}/{len(cuts)} cuts"
        )
    assert not diffs, diffs[:10]
    assert neg > 0
