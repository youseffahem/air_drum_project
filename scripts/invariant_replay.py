"""Phase 17 Task 17.2: safety invariants I1-I6 over the full replay set + system-level TEST-CAUSAL-1.

    python scripts/invariant_replay.py --executor-model M --executor-effort E [--quick]

Replay set (every recording and labelled SYNTHETIC session present in this repository; there is
no participant dataset yet, so the participant part of "the full replay set" is PENDING):

* developer recordings with raw frames: ``data/dev-captures/swing-L2-exp-{5,6,7}``,
  ``data/dev-sessions/dev-p05-swing-L2-exp-{5,6,7}``, ``data/raw/DEV/dev-p06-ingest-exp-5`` -> real
  perception -> live loop (``DecisionPipeline``) under three arm set-ups (A active / B active /
  C-GRU active, the others shadow);
* the SYNTHETIC P07 session ``data/raw/SYNTHETIC/synthetic-p07-labels``: its recorded observations
  through the live loop (three set-ups) and its causal tracks through the Phase 09 harness
  (arms A and B, ``CommitAuditor`` assertions);
* every SYNTHETIC scenario of ``app.synthetic`` (two noise levels) through the live loop.

Every live-loop replay runs the ``InvariantMonitor`` in ``collect`` mode: the MEASURED quantity is the
violation count (required 0) with the number of checks made per invariant. TEST-CAUSAL-1 (system
level, hardened build): for each developer recording and set-up, frames after a cut are replaced
(GARBAGE noise, REMOVED, SHIFTED from another recording); every record at frames <= cut must equal
the reference run (Phase 13 tolerance for model predictions).
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from _p13 import compare_records
from _p17 import MODEL_CONFIG, RULE_CONFIG, Ticker, add_executor_args, build_pipeline, evidence

from spacedrums.app.invariants import InvariantMonitor
from spacedrums.app.main import Perception
from spacedrums.app.synthetic import SCENARIOS, scenario
from spacedrums.capture import ReplayFrameSource
from spacedrums.commit import CommitAuditor, CommitSettings
from spacedrums.config import load_config
from spacedrums.contracts import FrameView, HandId, HandObservation, StickObservation
from spacedrums.data.feature_dataset import load_session
from spacedrums.eval.replay import replay
from spacedrums.geometry import ZoneRegistry
from spacedrums.prediction import RuleSettings

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = (
    "data/dev-captures/swing-L2-exp-5",
    "data/dev-captures/swing-L2-exp-6",
    "data/dev-captures/swing-L2-exp-7",
    "data/dev-sessions/dev-p05-swing-L2-exp-5",
    "data/dev-sessions/dev-p05-swing-L2-exp-6",
    "data/dev-sessions/dev-p05-swing-L2-exp-7",
    "data/raw/DEV/dev-p06-ingest-exp-5",
)
SYNTHETIC_SESSION = "data/raw/SYNTHETIC/synthetic-p07-labels"
SYNTHETIC_LABELS = "data/labels/synthetic-p07-labels"
SETUPS = {
    "A-active": {"config": RULE_CONFIG, "active": "A", "shadows": ("B",)},
    "B-active": {"config": RULE_CONFIG, "active": "B", "shadows": ("A",)},
    "C-active": {"config": MODEL_CONFIG, "active": "C-GRU", "shadows": ("A", "B")},
}


def live_loop(cfg, setup, frames, *, perception=None):
    pipe = build_pipeline(
        copy.deepcopy(cfg), active=setup["active"], shadows=setup["shadows"], clock=Ticker()
    )
    monitor = InvariantMonitor.for_pipeline(pipe, mode="collect")
    results = []
    for sample, payload in frames:
        obs = perception(payload) if perception is not None else payload
        r = pipe.step(sample, obs, t_now=sample.t_frame_available)
        monitor.observe(r, pipe)
        results.append(r)
    summary = monitor.finish()
    return results, summary, pipe


def recorded_observations(session_dir: Path):
    """(sample, observations) from a recorded session's frames.jsonl + observation streams."""
    src = ReplayFrameSource(session_dir)
    hands: dict[tuple[int, str], HandObservation] = {}
    sticks: dict[tuple[int, str], StickObservation] = {}
    for name, store, cls in (
        ("HandObservation.jsonl", hands, HandObservation),
        ("StickObservation.jsonl", sticks, StickObservation),
    ):
        for line in (session_dir / "records" / name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "frame_id" in row and "hand_id" in row:
                store[(row["frame_id"], row["hand_id"])] = cls.from_dict(row)
    out = []
    for sample in src:
        out.append(
            (
                sample,
                {h: (hands[(sample.frame_id, str(h))], sticks[(sample.frame_id, str(h))]) for h in HandId},
            )
        )
    return out


def record_rows(results):
    rows = []
    for r in results:
        for h, hf in r.hands.items():
            rows.append(("track", r.sample.frame_id, str(h), hf.track))
            for kind, pred in (("rule", hf.prediction), ("model", hf.model_prediction)):
                if pred is not None:
                    rows.append((kind, r.sample.frame_id, str(h), pred))
            for c in hf.candidates:
                rows.append(("candidate", r.sample.frame_id, str(h), c))
            for c in hf.commits:
                rows.append(("commit", r.sample.frame_id, str(h), c))
    return rows


def causal_check(cfg, setup, src, other, cut, rng):
    """TEST-CAUSAL-1 on the live loop: perturb frames > cut three ways; the prefix must not change."""
    reference, _, _ = run_capture(cfg, setup, src, None, cut=None)
    ref_rows = [row for row in record_rows(reference) if row[1] <= cut]
    ref_suffix = {
        (row[1], row[2]): row[3] for row in record_rows(reference) if row[0] == "track" and row[1] > cut
    }
    outcomes = {}
    for kind in ("GARBAGE", "REMOVED", "SHIFTED"):
        results, _, _ = run_capture(cfg, setup, src, (kind, other, rng), cut=cut)
        rows = [row for row in record_rows(results) if row[1] <= cut]
        suffix = {
            (row[1], row[2]): row[3] for row in record_rows(results) if row[0] == "track" and row[1] > cut
        }
        # non-vacuity: how many post-cut track records the perturbation actually changed or removed
        changed = sum(1 for key, track in ref_suffix.items() if suffix.get(key) != track)
        ok = len(rows) == len(ref_rows)
        max_dev = 0.0
        if ok:
            for a, b in zip(rows, ref_rows, strict=True):
                if a[:3] != b[:3]:
                    ok = False
                    break
                try:
                    dev = compare_records([a[3]], [b[3]], ignored=("t_inference_done", "t_candidate"))
                    max_dev = max(max_dev, dev["max_abs_deviation"])
                except AssertionError:
                    ok = False
                    break
        outcomes[kind] = {
            "passed": ok,
            "prefix_records": len(ref_rows),
            "max_abs_deviation": max_dev,
            "suffix_tracks": len(ref_suffix),
            "suffix_tracks_changed": changed,
        }
    return outcomes


def run_capture(cfg, setup, src, perturb, *, cut):
    perception = Perception(cfg)
    try:
        frames = []
        samples = list(src)
        if perturb is not None and perturb[0] == "REMOVED":
            samples = samples[: cut + 1]
        for i, sample in enumerate(samples):
            view = src.view(sample)
            if perturb is not None and i > cut:
                kind, other, rng = perturb
                if kind == "GARBAGE":
                    view = FrameView(sample=sample, roi=rng.integers(0, 256, view.roi.shape, dtype=np.uint8))
                elif kind == "SHIFTED":
                    alt = other.samples[i % len(other.samples)]
                    alt_view = other.view(alt)
                    view = FrameView(sample=sample, roi=alt_view.roi.copy(), full=None)
            frames.append((sample, view))
        return live_loop(cfg, setup, frames, perception=perception)
    finally:
        perception.close()


def harness_assertions(session_dir: Path, label_dir: Path):
    """Phase 09 harness replay of the SYNTHETIC P07 causal tracks with CommitAuditor (I1/I3/I4)."""
    session = load_session(session_dir, label_dir, selftest=True)
    cfg = load_config(session_dir / "config.snapshot.yaml")
    registry = ZoneRegistry.from_config(cfg["zones"])
    settings = CommitSettings.from_config(cfg)
    frames = [json.loads(line) for line in (session_dir / "frames.jsonl").read_text().splitlines()]
    drops = {row["frame_id"]: row["dropped_since_last"] for row in frames}
    out = {}
    for arm in ("A", "B"):
        result = replay(
            session.tracks,
            arm=arm,
            registry=registry,
            commit_settings=settings,
            v_min=cfg["geometry"]["v_min"],
            session_id=session.table.session_id,
            rule_settings=RuleSettings.from_config(cfg) if arm == "B" else None,
            dropped_by_frame=drops,
        )
        auditor = CommitAuditor(settings, registry)
        by_frame = defaultdict(dict)
        for t in session.tracks:
            by_frame[t.frame_id][t.hand_id] = t
        commits = defaultdict(list)
        for c in result.committed:
            commits[c.frame_id].append(c)
        violations = []
        for frame_id in sorted(by_frame):
            tracks = by_frame[frame_id]
            t = next(iter(tracks.values())).t_capture
            violations += auditor.audit_frame(
                frame_id=frame_id, t_capture=t, t_now=t, tracks=tracks, commits=commits.get(frame_id, [])
            )
        auditor.finish()
        out[arm] = {
            "commits": len(result.committed),
            "violations": len(violations),
            "first": [v.to_dict() for v in violations[:5]],
            **auditor.summary(),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-17")
    ap.add_argument("--slug", default="invariant-replay")
    add_executor_args(ap)
    args = ap.parse_args()
    with evidence(
        RULE_CONFIG,
        args,
        slug=args.slug + ("-quick" if args.quick else ""),
        task="17.2",
        description="Safety invariants over the full development replay set; TEST-CAUSAL-1 system level",
        output=args.output,
    ) as (run, _cfg):
        rows = []
        causal = []
        rng = np.random.default_rng(17)
        recordings = [p for p in RECORDINGS if (ROOT / p / "frames.jsonl").exists()]
        recordings = recordings[:1] if args.quick else recordings
        other = ReplayFrameSource(ROOT / RECORDINGS[1])
        for rec in recordings:
            src = ReplayFrameSource(ROOT / rec)
            for name, setup in SETUPS.items():
                cfg = load_config(setup["config"]).data
                results, summary, pipe = run_capture(cfg, setup, src, None, cut=None)
                rows.append(
                    {
                        "source": rec,
                        "kind": "DEV_CAPTURE (raw frames, real perception)",
                        "setup": name,
                        "frames": len(results),
                        "commits": sum(len(r.commits) for r in results),
                        "fallbacks": len(pipe.fallback_events),
                        **{k: summary[k] for k in ("violations", "violations_total", "checks")},
                    }
                )
                print(f"{rec} {name}: violations={summary['violations_total']}", flush=True)
                if rec.startswith("data/dev-captures") and not args.quick or rec == recordings[0]:
                    cut = len(src) // 2
                    causal.append(
                        {
                            "source": rec,
                            "setup": name,
                            "cut": cut,
                            **causal_check(cfg, setup, src, other, cut, rng),
                        }
                    )
        synthetic = ROOT / SYNTHETIC_SESSION
        if synthetic.exists():
            frames = recorded_observations(synthetic)
            for name, setup in SETUPS.items():
                cfg = load_config(setup["config"]).data
                results, summary, pipe = live_loop(cfg, setup, frames)
                rows.append(
                    {
                        "source": SYNTHETIC_SESSION,
                        "kind": "SYNTHETIC recorded observations",
                        "setup": name,
                        "frames": len(results),
                        "commits": sum(len(r.commits) for r in results),
                        "fallbacks": len(pipe.fallback_events),
                        **{k: summary[k] for k in ("violations", "violations_total", "checks")},
                    }
                )
            harness = harness_assertions(synthetic, ROOT / SYNTHETIC_LABELS)
        else:
            harness = {"status": "PENDING: SYNTHETIC P07 session not present"}
        for name, setup in SETUPS.items():
            cfg = load_config(setup["config"]).data
            registry = ZoneRegistry.from_config(cfg["zones"])
            for scen in SCENARIOS[:3] if args.quick else SCENARIOS:
                for noise, seed in ((0.0, 0), (0.004, 7)):
                    results, summary, pipe = live_loop(
                        cfg, setup, list(scenario(scen, registry, noise=noise, seed=seed))
                    )
                    rows.append(
                        {
                            "source": f"synthetic:{scen}:noise{noise}",
                            "kind": "SYNTHETIC scenario",
                            "setup": name,
                            "frames": len(results),
                            "commits": sum(len(r.commits) for r in results),
                            "fallbacks": len(pipe.fallback_events),
                            **{k: summary[k] for k in ("violations", "violations_total", "checks")},
                        }
                    )
        checks = defaultdict(int)
        for r in rows:
            for k, v in r["checks"].items():
                checks[k] += v
        totals = {
            "replays": len(rows),
            "frames": sum(r["frames"] for r in rows),
            "commits_audited": sum(r["commits"] for r in rows),
            "violations_total": sum(r["violations_total"] for r in rows),
            "checks": dict(sorted(checks.items())),
            "harness_violations": sum(
                v.get("violations", 0) for v in harness.values() if isinstance(v, dict)
            ),
            "causal_passed": all(c[k]["passed"] for c in causal for k in ("GARBAGE", "REMOVED", "SHIFTED")),
            "participant_replay_set": "PENDING: no participant dataset (ds-v1.0) exists",
        }
        report = {"totals": totals, "rows": rows, "harness": harness, "test_causal_1": causal}
        (run.dir / "invariant-replay.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(totals, indent=2), flush=True)
    return (
        0
        if totals["violations_total"] == 0 and totals["harness_violations"] == 0 and totals["causal_passed"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
