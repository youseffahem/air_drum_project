"""Phase 07, Task 07.7 — validate label sets (``RESULT: PASS|FAIL``).

    python scripts/validate_labels.py --all
    python scripts/validate_labels.py --labels data/labels/<session> --session data/raw/<p>/<session>
    python scripts/validate_labels.py --selftest        # negative cases on a SYNTHETIC label set

Checks referential integrity with the session and its segments, monotone times, one positive per
episode, no positive inside a quarantined segment, provenance and version agreement, the
non-causality flags, the ``has_phys_gt`` three-level invariant and the separation of the causal and
reference trajectories. A clean run prints no violation and exits 0.

``--selftest`` additionally *injects* each failure mode into a copy of a generated SYNTHETIC label
set and asserts the validator catches it: a validator that never fails is not evidence.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import LABELS_ROOT, find_label_dirs, find_sessions, git_sha, use_utf8_stdout  # noqa: E402

from spacedrums.data.labels.generate import generate_labels, read_label_set, read_labels  # noqa: E402
from spacedrums.data.labels.schema import (  # noqa: E402
    LABEL_SET_FILENAME,
    LABELS_FILENAME,
    label_set_hash,
)
from spacedrums.data.labels.validate import validate_label_dir, validate_labels  # noqa: E402


def _session_for(label_dir: Path) -> Path | None:
    for candidate in find_sessions():
        if candidate.name == label_dir.name:
            return candidate
    return None


def _mutations() -> dict[str, Any]:
    """Named corruptions of a valid label set, each expected to raise a specific violation code."""

    def _event(labels):
        """The first EVENT-level label; corrupting an INTERVAL one would only test the schema."""
        return next(r for r in labels if r["level"] == "EVENT")

    def bad_time(labels, label_set):
        rec = _event(labels)
        rec["t_event"] += 10_000.0
        if rec["t_impact_est"] is not None:
            rec["t_impact_est"] = rec["t_event"]
        return labels, label_set

    def bad_frame(labels, label_set):
        _event(labels)["frames"]["before_event"] = 10_000_000
        return labels, label_set

    def bad_zone(labels, label_set):
        for rec in labels:
            if rec["zone_id"]:
                rec["zone_id"] = "not_a_zone"
                break
        return labels, label_set

    def duplicate_positive(labels, label_set):
        pos = next(r for r in labels if r["label_class"] == "POSITIVE")
        clone = copy.deepcopy(pos)
        clone["label_id"] = pos["label_id"] + "-dup"
        clone["t_event"] = pos["t_event"] + 0.001
        clone["t_impact_est"] = clone["t_event"]
        labels.append(clone)
        label_set["counts"]["by_class"]["POSITIVE"] += 1
        label_set["counts"]["total"] += 1
        label_set["set_hash"] = label_set_hash(label_set)
        return labels, label_set

    def duplicate_episode(labels, label_set):
        pos = [r for r in labels if r["label_class"] == "POSITIVE"]
        pos[1]["episode_id"] = pos[0]["episode_id"]
        return labels, label_set

    def malformed(labels, label_set):
        labels[0]["label_class"] = "NOT_A_CLASS"
        return labels, label_set

    def provenance_mismatch(labels, label_set):
        labels[0]["provenance"] = dict(labels[0]["provenance"])
        labels[0]["provenance"]["smoother_id"] = "savgol-centred-v1"
        return labels, label_set

    def version_mismatch(labels, label_set):
        labels[0]["labels_version"] = "labels-v9.9"
        return labels, label_set

    def labels_hash_mismatch(labels, label_set):
        label_set["provenance"] = dict(label_set["provenance"])
        label_set["provenance"]["labels_hash"] = "sha256:" + "1" * 64
        label_set["set_hash"] = label_set_hash(label_set)
        return labels, label_set

    def causal_flag(labels, label_set):
        labels[0]["causal"] = True
        return labels, label_set

    def runtime_copied(labels, label_set):
        rec = next(r for r in labels if r["t_impact_est"] is not None)
        rec["runtime_reference"]["causal_t_impact_est"] = rec["t_impact_est"]
        return labels, label_set

    def provenance_kind(labels, label_set):
        label_set["source_kind"] = "PARTICIPANT"
        label_set["set_hash"] = label_set_hash(label_set)
        return labels, label_set

    def phys_without_pad(labels, label_set):
        rec = next(r for r in labels if r["label_class"] == "POSITIVE")
        rec["t_impact_phys"] = rec["t_impact_est"] + 0.004
        rec["phys"] = {
            "onset_index": 0,
            "onset_t_mono": rec["t_impact_phys"],
            "residual_s": 0.004,
            "mic_latency_bound_s": 0.005,
            "pad_zone_id": rec["zone_id"],
            "sync_residual_rms_s": None,
        }
        return labels, label_set

    return {
        "invalid timestamp (outside the session)": (bad_time, {"TIME_OUT_OF_SESSION", "FUTURE_LEAKAGE"}),
        "invalid frame reference": (bad_frame, {"FRAME_UNKNOWN"}),
        "impossible zone id": (bad_zone, {"ZONE_UNKNOWN"}),
        "duplicate / conflicting positive": (duplicate_positive, {"POSITIVE_CONFLICT"}),
        "two positives in one episode": (duplicate_episode, {"EPISODE_DUPLICATE"}),
        "malformed annotation": (malformed, {"SCHEMA_INVALID"}),
        "provenance mismatch": (provenance_mismatch, {"PROVENANCE_MISMATCH"}),
        "version mismatch": (version_mismatch, {"VERSION_MISMATCH"}),
        "labels_hash mismatch": (labels_hash_mismatch, {"LABELS_HASH_MISMATCH"}),
        "causal flag flipped": (causal_flag, {"SCHEMA_INVALID", "CAUSAL_FLAG"}),
        "runtime candidate time copied into ground truth": (runtime_copied, {"RUNTIME_TIME_COPIED"}),
        "SYNTHETIC set relabelled PARTICIPANT": (provenance_kind,
                                                 {"SOURCE_KIND_NOT_ADMISSIBLE", "VERSION_MISMATCH",
                                                  "SET_SCHEMA_INVALID"}),
        "physical GT on a non-PAD strike": (phys_without_pad, {"PHYS_INVARIANT", "SCHEMA_INVALID"}),
    }


def selftest() -> int:
    """Generate a SYNTHETIC label set, confirm it is clean, then confirm each corruption is caught."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "data"))
    from data_helpers import make_session

    tmp = Path(tempfile.mkdtemp(prefix="p07-validate-"))
    try:
        session_dir, meta, _ = make_session(tmp / "raw", session_id="synthetic-p07-validate")
        result = generate_labels(session_dir, tmp / "labels",
                                 dataset_version="ds-v0.0-selftest-validate", git_sha=git_sha())
        clean = validate_label_dir(result.label_dir, session_dir=session_dir)
        print(f"[selftest] generated {len(result.labels)} SYNTHETIC labels "
              f"({result.by_class()})")
        print(f"[selftest] validator on the clean set: "
              f"{'CLEAN' if not clean else f'{len(clean)} violations'}")
        for v in clean[:5]:
            print(f"    - {v}")
        ok = not clean
        base_labels = read_labels(result.label_dir / LABELS_FILENAME)
        base_set = read_label_set(result.label_dir / LABEL_SET_FILENAME)
        frame_ids = [json.loads(line)["frame_id"]
                     for line in (session_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()
                     if line.strip()]
        from spacedrums.config import load_config

        zone_ids = [z["zone_id"] for z in load_config(session_dir / "config.snapshot.yaml")["zones"]]
        print("\n[selftest] negative cases (each corruption must be caught):")
        for name, (mutate, expected) in _mutations().items():
            try:
                labels, label_set = mutate(copy.deepcopy(base_labels), copy.deepcopy(base_set))
            except StopIteration:
                # The generated set has no label of the class this corruption needs. Skipping is
                # reported, never silently counted as a pass.
                print(f"  SKIPPED {name}: the SYNTHETIC set contains no label of the needed class")
                ok = False
                continue
            found = {v.code for v in validate_labels(labels, label_set, meta=meta,
                                                     zone_ids=zone_ids, frame_ids=frame_ids)}
            caught = bool(found & expected)
            ok = ok and caught
            codes = sorted(found & expected) or sorted(found)
            print(f"  {'CAUGHT ' if caught else 'MISSED '} {name}: {codes}")
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", action="append", default=[], help="label directory (repeatable)")
    ap.add_argument("--session", default=None, help="the session the labels came from")
    ap.add_argument("--all", action="store_true", help="every label set under data/labels/")
    ap.add_argument("--selftest", action="store_true", help="SYNTHETIC generate + negative cases")
    ap.add_argument("--labels-root", default=str(LABELS_ROOT))
    args = ap.parse_args(argv)
    use_utf8_stdout()

    if args.selftest:
        return selftest()
    dirs = find_label_dirs(Path(args.labels_root)) if args.all else [Path(p) for p in args.labels]
    if not dirs:
        print("[validate] no label set found — nothing to validate (labels are PENDING)")
        return 0
    total = 0
    for d in dirs:
        session = Path(args.session) if args.session else _session_for(d)
        violations = validate_label_dir(d, session_dir=session)
        total += len(violations)
        print(f"[{d.name}] {'CLEAN' if not violations else f'{len(violations)} violations'}"
              f"{'' if session else '  (session not found: referential checks skipped)'}")
        for v in violations:
            print(f"    - {v}")
    print(f"\nRESULT: {'PASS' if total == 0 else 'FAIL'} ({total} violations)")
    return 0 if total == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
