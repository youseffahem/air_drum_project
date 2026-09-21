"""Phase 06, Task 06.3 evidence — re-track a recorded session from its raw frames and compare the
regenerated derived records with the recorded ones (architecture.md section 12.3; the "pilot file
re-tracked to confirm derived records regenerate" check of ADR-0019).

    python scripts/regenerate_session.py <session_dir> [--out <dir>] [--max-frames N] [--keep]

Replays ``<session_dir>/frames.jsonl`` + PNGs through the live application's perception and decision
pipeline (``spacedrums.app.main --source replay --record --regenerated``), so the regenerated streams
carry ``producer = REGENERATED`` with the current ``git_sha`` / ``config_hash``, then compares, record
by record, the streams that must be identical when code and config are unchanged: HandObservation,
StickObservation, TrackState, StrikeCandidate, CommittedStrike and AudioEvent (TimingRecord and
TrajectoryPrediction carry live processing stamps and are compared on their decision fields only).

The comparison needs real pixels: it is meaningful on a DEV CAPTURE session (or a pilot / participant
session) and reports "not comparable" on a SYNTHETIC session, whose frames are blank. A difference is
reported, never hidden: it means the perception stage is not deterministic for these frames, or the
code / config changed since the recording (both are stated in the output).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import RunLog, git_sha  # noqa: E402

from spacedrums.app.main import build_parser, run  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.data.metadata import METADATA_FILENAME, classification_label  # noqa: E402
from spacedrums.timing.logger import read_record_stream  # noqa: E402

# Streams compared record by record. Live processing stamps (wall-clock of this run) and the
# session-id prefix of opaque ids are not part of the derived content and are normalised away.
STREAMS = (
    "HandObservation",
    "StickObservation",
    "TrackState",
    "TrajectoryPrediction",
    "StrikeCandidate",
    "CommittedStrike",
    "AudioEvent",
    "TimingRecord",
)
LIVE_STAMPS = {
    "t_candidate",
    "t_inference_done",
    "t_tracking_done",
    "t_features_done",
    "t_commit",
    "t_audio_scheduled",
    "t_audio_out_est",
    "audio_late_s",
    "t_target_play",
    "refractory_until",
    "t_impact_target",
}
ID_FIELDS = {"candidate_id", "strike_id", "episode_id"}
NUMERIC_TOL = 1e-9  # decision-identical if every number agrees within this (floating-point noise only)


def _normalise(rec: dict, session_id: str) -> dict:
    out = {}
    for k, v in rec.items():
        if k in LIVE_STAMPS:
            continue
        if k in ID_FIELDS and isinstance(v, str) and v.startswith(session_id):
            v = v[len(session_id) :]
        out[k] = v
    return out


def _max_abs_diff(x, y) -> float:
    """Largest absolute numeric difference between two equally shaped JSON values (inf if shapes differ
    or a non-numeric leaf differs)."""
    if isinstance(x, bool) or isinstance(y, bool):
        return 0.0 if x == y else float("inf")
    if isinstance(x, int | float) and isinstance(y, int | float):
        return abs(float(x) - float(y))
    if isinstance(x, dict) and isinstance(y, dict):
        if x.keys() != y.keys():
            return float("inf")
        return max((_max_abs_diff(x[k], y[k]) for k in x), default=0.0)
    if isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            return float("inf")
        return max((_max_abs_diff(a, b) for a, b in zip(x, y, strict=True)), default=0.0)
    return 0.0 if x == y else float("inf")


def compare_streams(original: Path, regenerated: Path, *, tol: float = NUMERIC_TOL) -> dict:
    """Three verdicts per stream: bit-identical, decision-identical (only numeric noise <= tol after
    normalising live stamps and id prefixes) or different."""
    sid0 = read_record_stream(original / "records/TrackState.jsonl")[0]["session_id"]
    sid1 = read_record_stream(regenerated / "records/TrackState.jsonl")[0]["session_id"]
    out: dict = {
        "streams": {},
        "bit_identical": True,
        "decision_identical": True,
        "numeric_tol": tol,
        "max_abs_diff": 0.0,
    }
    for name in STREAMS:
        rel = "timing.jsonl" if name == "TimingRecord" else f"records/{name}.jsonl"
        h0, a = read_record_stream(original / rel)
        h1, b = read_record_stream(regenerated / rel)
        n_bit = sum(1 for x, y in zip(a, b, strict=False) if x != y) + abs(len(a) - len(b))
        na = [_normalise(r, sid0) for r in a]
        nb = [_normalise(r, sid1) for r in b]
        diffs = [_max_abs_diff(x, y) for x, y in zip(na, nb, strict=False)]
        worst = max(diffs, default=0.0) if len(a) == len(b) else float("inf")
        n_decision = sum(1 for d in diffs if d > tol) + abs(len(a) - len(b))
        out["streams"][name] = {
            "n_original": len(a),
            "n_regenerated": len(b),
            "n_bit_differing": n_bit,
            "n_decision_differing": n_decision,
            "max_abs_diff": None if worst == float("inf") else worst,
            "producer": (h0.get("producer"), h1.get("producer")),
            "same_config_hash": h0.get("config_hash") == h1.get("config_hash"),
            "same_git_sha": h0.get("git_sha") == h1.get("git_sha"),
        }
        out["bit_identical"] = out["bit_identical"] and n_bit == 0
        out["decision_identical"] = out["decision_identical"] and n_decision == 0
        if worst != float("inf"):
            out["max_abs_diff"] = max(out["max_abs_diff"], worst)
    out["verdict"] = (
        "BIT-IDENTICAL"
        if out["bit_identical"]
        else ("DECISION-IDENTICAL" if out["decision_identical"] else "DIFFERENT")
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_dir", type=Path)
    ap.add_argument(
        "--out", type=Path, default=None, help="where to write the regenerated session (default: temp)"
    )
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--no-runlog", action="store_true")
    args = ap.parse_args(argv)
    sd = args.session_dir
    meta = (
        json.loads((sd / METADATA_FILENAME).read_text(encoding="utf-8"))
        if (sd / METADATA_FILENAME).exists()
        else {}
    )
    kind = meta.get("session_kind", "DEV_CAPTURE")
    label = classification_label(kind)
    if kind == "SYNTHETIC":
        print(
            f"[regenerate] {sd.name}: SYNTHETIC session (blank frames) - perception cannot re-derive "
            "generated observations; not comparable. Use a DEV CAPTURE / pilot / participant session."
        )
        return 0
    out_root = args.out or Path(tempfile.mkdtemp(prefix="p06-regen-"))
    session_id = f"{sd.name}-regen"
    argv_app = [
        "--config",
        str(sd / "config.snapshot.yaml"),
        "--source",
        "replay",
        "--session-dir",
        str(sd),
        "--record",
        "--regenerated",
        "--no-window",
        "--no-audio",
        "--output-dir",
        str(out_root),
        "--session-id",
        session_id,
        "--arm",
        meta.get("arm_active", "A"),
    ]
    if args.max_frames is not None:
        argv_app += ["--max-frames", str(args.max_frames)]

    def do() -> dict:
        summary = run(build_parser().parse_args(argv_app))
        regen = Path(summary["session_dir"])
        cmp = compare_streams(sd, regen)
        cmp["session_id"] = meta.get("session_id", sd.name)
        cmp["session_kind"] = kind
        cmp["label"] = label
        cmp["regenerated_dir"] = str(regen)
        cmp["frames"] = summary["frames"]
        cmp["note"] = {
            "BIT-IDENTICAL": "every derived record re-derived bit for bit from the raw frames",
            "DECISION-IDENTICAL": (
                "every decision (statuses, candidates, commits, zones, frames) re-derived identically; "
                f"numeric fields differ only by floating-point noise (max {cmp['max_abs_diff']:.2e} "
                f"<= tol {cmp['numeric_tol']:.0e}), "
                "i.e. the perception stage is deterministic in content but not bit-exact across processes"
            ),
            "DIFFERENT": "decisions differ: perception non-determinism or a code / config change since "
            "the recording "
            "(see same_git_sha / same_config_hash per stream)",
        }[cmp["verdict"]]
        return cmp

    if args.no_runlog:
        cmp = do()
    else:
        cfg = load_config(sd / "config.snapshot.yaml")
        with RunLog(
            phase="06",
            task="06.3",
            slug="p06-regenerate-session",
            config=cfg,
            experiments_dir=args.experiments_dir,
            description=(
                f"Task 06.3 re-track check on {sd.name} [{kind}]: regenerate derived records from raw "
                f"frames and compare. {label}."
            ),
        ) as runlog:
            cmp = do()
            runlog.write_json_artefact("regenerate_session.json", cmp)
            runlog.finish(
                {
                    "label": kind,
                    "verdict": cmp["verdict"],
                    "bit_identical": cmp["bit_identical"],
                    "decision_identical": cmp["decision_identical"],
                    "max_abs_diff": cmp["max_abs_diff"],
                    "frames": cmp["frames"],
                }
            )
    print(f"[regenerate] {cmp['session_id']} [{kind}] :: {label}")
    for name, st in cmp["streams"].items():
        print(
            f"  {name:<20} orig {st['n_original']:>6} regen {st['n_regenerated']:>6} "
            f"bit-diff {st['n_bit_differing']:>4} decision-diff {st['n_decision_differing']:>4} "
            f"max|d| {st['max_abs_diff']} producer {st['producer']}"
        )
    print(f"RESULT: {cmp['verdict']} - {cmp['note']} (git_sha now {git_sha()[:8]})")
    if not args.keep and args.out is None:
        shutil.rmtree(out_root, ignore_errors=True)
    return 0 if cmp["decision_identical"] else 2


if __name__ == "__main__":
    sys.exit(main())
