"""Phase 05 session summaries: counts, timing decomposition, informal B-vs-A comparison, synthetic truth
evaluation (Tasks 05.4, 05.9, 05.10; playability and induced-loss self-tests).

**Scope and labels.** This is the Phase 05 *developer sanity-check* machinery. The canonical
evaluation harness (README section 10: event matching, PLT/FP/FN/TE/zone accuracy on labelled
participant data) is Phase 09's ``eval`` and will be implemented there once; nothing here is a
research result. Two references exist:

* ``compare_arms`` — the **reactive arm's observed crossing** (``t_impact_est``) is the reference for
  the rule arm's commits: informal lead time ``L_pred = t_impact_est(A) - t_commit(B)``, timing error
  ``TE_pred = t_impact_pred(B) - t_impact_est(A)``, zone agreement, unmatched counts. Label:
  *developer sanity check — reactive reference, not ground truth*.
* ``evaluate_against_truth`` — a **SYNTHETIC** analytic crossing list (``app.synthetic``) is the
  reference: matched / false-positive / false-negative / duplicate counts, lead time and timing error
  per arm. Label: *SYNTHETIC unit-test evidence*; never real-world performance.

Matching (both): per hand, greedy one-to-one by ascending |t_ref(strike) - t_ref(reference)|, pair
accepted only if the difference <= ``window_s`` (README section 10.1 method; ``window_s`` is a
provisional value here, Phase 09 sweeps and freezes it). Zone agreement is reported, not required.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spacedrums.contracts import CommittedStrike, StrikeCandidate, TimingRecord
from spacedrums.timing.decomposition import decompose, decomposition_table, stats
from spacedrums.timing.logger import read_record_stream

DEFAULT_WINDOW_S = 0.10  # provisional matching tolerance W (Phase 09 sweeps it)


# ----------------------------------------------------------------------------- loading


def load_session(session_dir: str | Path) -> dict[str, Any]:
    d = Path(session_dir)
    out: dict[str, Any] = {"dir": str(d), "session": {}}
    if (d / "session.json").exists():
        out["session"] = json.loads((d / "session.json").read_text(encoding="utf-8"))
    for name in ("StrikeCandidate", "CommittedStrike", "TrajectoryPrediction", "TrackState", "AudioEvent"):
        path = d / "records" / f"{name}.jsonl"
        out[name] = read_record_stream(path)[1] if path.exists() else []
    tpath = d / "timing.jsonl"
    out["TimingRecord"] = read_record_stream(tpath)[1] if tpath.exists() else []
    return out


# ----------------------------------------------------------------------------- matching


def _greedy_match(
    strikes: Sequence[tuple[int, str, str, float]],
    refs: Sequence[tuple[int, str, str, float]],
    window_s: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Greedy one-to-one matching per hand. Items are (index, hand, zone, t_ref)."""
    pairs = sorted(
        (
            (abs(s[3] - r[3]), i, j)
            for i, s in enumerate(strikes)
            for j, r in enumerate(refs)
            if s[1] == r[1] and abs(s[3] - r[3]) <= window_s
        ),
        key=lambda x: (x[0], x[1], x[2]),
    )
    used_s: set[int] = set()
    used_r: set[int] = set()
    matched: list[tuple[int, int]] = []
    for _, i, j in pairs:
        if i in used_s or j in used_r:
            continue
        used_s.add(i)
        used_r.add(j)
        matched.append((i, j))
    return (
        matched,
        [i for i in range(len(strikes)) if i not in used_s],
        [j for j in range(len(refs)) if j not in used_r],
    )


def _t_ref(strike: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> float:
    """Reference time of a commit: t_impact_pred (anticipatory) or the observed t_impact_est (reactive)."""
    c = candidates.get(strike["candidate_id"])
    if c is not None and c.get("t_impact_est") is not None:
        return float(c["t_impact_est"])
    return float(strike["t_impact_target"])


def compare_arms(
    commits: Sequence[dict[str, Any]],
    candidates: Sequence[dict[str, Any]],
    *,
    window_s: float = DEFAULT_WINDOW_S,
) -> dict[str, Any]:
    """Informal B-vs-A comparison on one session (reactive arm = reference, not ground truth)."""
    cand = {c["candidate_id"]: c for c in candidates}
    a = [s for s in commits if s["arm"] == "A"]
    b = [s for s in commits if s["arm"] == "B"]
    a_items = [(i, s["hand_id"], s["zone_id"], _t_ref(s, cand)) for i, s in enumerate(a)]
    b_items = [(i, s["hand_id"], s["zone_id"], float(s["t_impact_target"])) for i, s in enumerate(b)]
    matched, b_unmatched, a_unmatched = _greedy_match(b_items, a_items, window_s)
    lead = [a_items[j][3] - float(b[i]["t_commit"]) for i, j in matched]
    advance = [float(a[j]["t_commit"]) - float(b[i]["t_commit"]) for i, j in matched]
    te = [b_items[i][3] - a_items[j][3] for i, j in matched]
    zone_ok = [b[i]["zone_id"] == a[j]["zone_id"] for i, j in matched]
    lead_a = [a_items[i][3] - float(a[i]["t_commit"]) for i in range(len(a))]
    return {
        "label": "developer sanity check - reactive arm as reference, not ground truth; "
        "not an experimental result",
        "window_s": window_s,
        "n_A": len(a),
        "n_B": len(b),
        "n_matched": len(matched),
        "n_B_unmatched": len(b_unmatched),
        "n_A_unmatched": len(a_unmatched),
        "zone_agreement": (sum(zone_ok) / len(zone_ok)) if zone_ok else None,
        # L_pred (README 5.4) with the reactive arm's observed crossing as the reference impact time
        "L_pred_B_vs_A_s": stats(lead).to_dict(),
        "L_pred_B_positive_fraction": (sum(1 for v in lead if v > 0) / len(lead)) if lead else None,
        # commit advance: how much earlier the rule arm committed than the reactive arm did
        # (t_commit(A) - t_commit(B))
        "commit_advance_B_vs_A_s": stats(advance).to_dict(),
        "TE_pred_B_vs_A_s": stats(te).to_dict(),
        "L_pred_A_s": stats(lead_a).to_dict(),  # by construction <= 0 (commit after the observed crossing)
        "pairs": [
            {
                "B": b[i]["strike_id"],
                "A": a[j]["strike_id"],
                "L_pred_s": lead[k],
                "commit_advance_s": advance[k],
                "TE_pred_s": te[k],
                "zone_agree": zone_ok[k],
            }
            for k, (i, j) in enumerate(matched)
        ],
    }


def evaluate_against_truth(
    commits: Sequence[dict[str, Any]],
    candidates: Sequence[dict[str, Any]],
    truth: Sequence[dict[str, Any]],
    *,
    window_s: float = DEFAULT_WINDOW_S,
) -> dict[str, Any]:
    """Per-arm counts against a SYNTHETIC analytic crossing list (unit-test evidence only)."""
    cand = {c["candidate_id"]: c for c in candidates}
    refs = [(j, t["hand_id"], t["zone_id"], float(t["t_cross"])) for j, t in enumerate(truth)]
    out: dict[str, Any] = {
        "label": "SYNTHETIC truth evaluation - unit-test evidence, not real-world performance",
        "window_s": window_s,
        "n_truth": len(truth),
        "arms": {},
    }
    for arm in sorted({s["arm"] for s in commits}):
        arm_commits = [s for s in commits if s["arm"] == arm]
        items = [(i, s["hand_id"], s["zone_id"], _t_ref(s, cand)) for i, s in enumerate(arm_commits)]
        matched, unmatched_s, unmatched_r = _greedy_match(items, refs, window_s)
        lead = [refs[j][3] - float(arm_commits[i]["t_commit"]) for i, j in matched]
        te = [items[i][3] - refs[j][3] for i, j in matched]
        zone_ok = [arm_commits[i]["zone_id"] == truth[j]["zone_id"] for i, j in matched]
        # duplicates: unmatched commits that fall within the window of an already-matched truth event
        dup = 0
        for i in unmatched_s:
            s = items[i]
            if any(r[1] == s[1] and abs(r[3] - s[3]) <= window_s for _, jj in matched for r in [refs[jj]]):
                dup += 1
        out["arms"][arm] = {
            "n_commits": len(arm_commits),
            "n_shadow": sum(1 for s in arm_commits if s["shadow"]),
            "n_matched": len(matched),
            "false_positives": len(unmatched_s) - dup,
            "duplicates": dup,
            "false_negatives": len(unmatched_r),
            "fp_rate": ((len(unmatched_s) - dup) / len(arm_commits)) if arm_commits else None,
            "fn_rate": (len(unmatched_r) / len(truth)) if truth else None,
            "zone_accuracy": (sum(zone_ok) / len(zone_ok)) if zone_ok else None,
            "L_pred_s": stats(lead).to_dict(),
            "L_pred_positive_fraction": (sum(1 for v in lead if v > 0) / len(lead)) if lead else None,
            "TE_s": stats(te).to_dict(),
        }
    return out


# ----------------------------------------------------------------------------- session-level


def count_records(session: dict[str, Any]) -> dict[str, Any]:
    commits = session["CommittedStrike"]
    cands = session["StrikeCandidate"]
    return {
        "frames": session["session"].get("frames"),
        "predictions": len(session["TrajectoryPrediction"]),
        "candidates": {src: sum(1 for c in cands if c["source"] == src) for src in ("REACTIVE", "RULE")},
        "commits": {arm: sum(1 for c in commits if c["arm"] == arm) for arm in ("A", "B")},
        "commits_shadow": sum(1 for c in commits if c["shadow"]),
        "commits_sounding": sum(1 for c in commits if not c["shadow"]),
        "audio_events": len(session["AudioEvent"]),
        "commits_by_hand_zone": _by_hand_zone(commits),
        "track_status_frames": _status_counts(session["TrackState"]),
    }


def _by_hand_zone(commits: Sequence[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in commits:
        key = f"{c['arm']}:{c['hand_id']}:{c['zone_id']}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _status_counts(tracks: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for t in tracks:
        h = out.setdefault(t["hand_id"], {})
        h[t["status"]] = h.get(t["status"], 0) + 1
    return out


def commits_during_non_valid(commits: Sequence[dict[str, Any]], tracks: Sequence[dict[str, Any]]) -> int:
    """Safety count (must be 0): commits on a frame whose hand status was not VALID."""
    status = {(t["frame_id"], t["hand_id"]): t["status"] for t in tracks}
    return sum(1 for c in commits if status.get((c["frame_id"], c["hand_id"])) != "VALID")


def summarise_session(
    session_dir: str | Path,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    truth: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = load_session(session_dir)
    timing = [TimingRecord.from_dict(r) for r in s["TimingRecord"]]
    dec = decompose(timing, live=(s["session"].get("producer") == "LIVE"))
    out = {
        "session_dir": s["dir"],
        "session": {k: v for k, v in s["session"].items() if k != "summary"},
        "counts": count_records(s),
        "commits_during_non_valid": commits_during_non_valid(s["CommittedStrike"], s["TrackState"]),
        "timing_decomposition": dec,
        "timing_table_markdown": decomposition_table(dec),
        "arm_comparison": compare_arms(s["CommittedStrike"], s["StrikeCandidate"], window_s=window_s),
    }
    if truth is not None:
        out["synthetic_truth_evaluation"] = evaluate_against_truth(
            s["CommittedStrike"], s["StrikeCandidate"], truth, window_s=window_s
        )
    return out


def commits_from_results(commits: Sequence[CommittedStrike], candidates: Sequence[StrikeCandidate]):
    """In-memory variant for tests: dict views of records."""
    return [c.to_dict() for c in commits], [c.to_dict() for c in candidates]


__all__ = [
    "DEFAULT_WINDOW_S",
    "commits_during_non_valid",
    "commits_from_results",
    "compare_arms",
    "count_records",
    "evaluate_against_truth",
    "load_session",
    "summarise_session",
]
