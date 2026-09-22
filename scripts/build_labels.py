"""Phase 07, Tasks 07.2 / 07.3 — generate the label set of one or more recorded sessions.

    python scripts/build_labels.py --session data/raw/DEV/dev-... [--out data/labels]
    python scripts/build_labels.py --all --dataset-version ds-v0.0-selftest-dev
    python scripts/build_labels.py --synthetic            # self-test on a generated session

Per session it writes ``<out>/<session_id>/``:

    tracks_causal.jsonl      the frozen Phase 03 tracker's TrackState stream, copied unchanged
    tracks_reference.jsonl   the NON-CAUSAL smoothed reference trajectory (labels only)
    labels.jsonl             the LabelRecords
    labels.meta.json         the label set: provenance, counts, QC state, file hashes

Determinism is part of the contract: re-running on the same session with the same options
reproduces byte-identical ``labels.jsonl`` and the same ``set_hash`` (``--check-determinism``
verifies it in-process).

Kind gating: a SYNTHETIC or DEV CAPTURE session can only be labelled into a
``ds-v0.0-selftest*`` dataset version. The script refuses anything else rather than relabelling
material (integrity I-4).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import (  # noqa: E402
    LABELS_ROOT,
    add_common_options,
    check_dataset_version,
    find_sessions,
    git_sha,
    smoother_from_args,
    thresholds_from_args,
    use_utf8_stdout,
)

from spacedrums.data.labels.generate import generate_labels  # noqa: E402
from spacedrums.data.labels.schema import LABELS_FILENAME  # noqa: E402
from spacedrums.data.labels.validate import leakage_report, validate_label_dir  # noqa: E402
from spacedrums.data.metadata import METADATA_FILENAME, SessionMetadata  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--session", action="append", default=[], help="session directory (repeatable)")
    src.add_argument("--all", action="store_true", help="every session under data/raw/")
    src.add_argument("--synthetic", action="store_true",
                     help="generate a SYNTHETIC session in a temporary directory and label it")
    ap.add_argument("--out", default=str(LABELS_ROOT))
    ap.add_argument("--check-determinism", action="store_true",
                    help="generate twice and compare labels.jsonl byte for byte")
    ap.add_argument("--validate", action="store_true", help="run the label validator afterwards")
    add_common_options(ap)
    return ap


def _synthetic_session(tmp: Path) -> Path:
    """A small SYNTHETIC session produced by the Phase 05/06 record path (no camera, no person)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "data"))
    from data_helpers import make_session

    session_dir, _, _ = make_session(tmp / "raw", session_id="synthetic-p07-selftest")
    return session_dir


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    use_utf8_stdout()
    try:
        kind = check_dataset_version(args.dataset_version)
    except ValueError as exc:
        print(f"[refused] {exc}")
        return 2
    print(f"[labels] dataset_version {args.dataset_version} ({kind}) labels_version "
          f"{args.labels_version}")
    print(f"[labels] smoother {args.smoother} max_gap {args.max_gap_s} s | "
          f"interpolation {args.interpolation}")

    tmp: Path | None = None
    if args.synthetic:
        tmp = Path(tempfile.mkdtemp(prefix="p07-selftest-"))
        sessions = [_synthetic_session(tmp)]
        out_root = Path(args.out) if args.out != str(LABELS_ROOT) else tmp / "labels"
    else:
        sessions = find_sessions() if args.all else [Path(s) for s in args.session]
        out_root = Path(args.out)
    if not sessions:
        print("[labels] no session found — nothing to label (participant data is PENDING)")
        return 0

    rc = 0
    try:
        for session_dir in sessions:
            if not (session_dir / METADATA_FILENAME).exists():
                print(f"\n[session] {session_dir}")
                print("  [refused] no metadata.json: not a recorded session directory")
                rc = max(rc, 1)
                continue
            meta = SessionMetadata.read(session_dir)
            print(f"\n[session] {meta.session_id} ({meta.kind}, participant {meta.data['participant_id']})")
            try:
                result = generate_labels(
                    session_dir,
                    out_root,
                    dataset_version=args.dataset_version,
                    thresholds=thresholds_from_args(args),
                    smoother=smoother_from_args(args),
                    interpolation=args.interpolation,
                    labels_version=args.labels_version,
                    git_sha=git_sha(),
                )
            except ValueError as exc:
                print(f"  [refused] {exc}")
                rc = max(rc, 1)
                continue
            print(f"  labels: {len(result.labels)} {result.by_class()}")
            print(f"  set_hash: {result.label_set['set_hash']}")
            print(f"  wrote: {', '.join(p.name for p in result.written)}")
            rep = leakage_report(result.label_dir)
            print(f"  separation check (criterion 2): causal={rep['causal_record_type']} "
                  f"reference_is_record_stream={rep['reference_is_record_stream']} ok={rep['ok']}")
            if not rep["ok"]:
                rc = max(rc, 1)
            if args.check_determinism:
                second = Path(tempfile.mkdtemp(prefix="p07-determinism-"))
                try:
                    again = generate_labels(
                        session_dir,
                        second,
                        dataset_version=args.dataset_version,
                        thresholds=thresholds_from_args(args),
                        smoother=smoother_from_args(args),
                        interpolation=args.interpolation,
                        labels_version=args.labels_version,
                        git_sha=git_sha(),
                    )
                    a = (result.label_dir / LABELS_FILENAME).read_bytes()
                    b = (again.label_dir / LABELS_FILENAME).read_bytes()
                    same = a == b and result.label_set["set_hash"] == again.label_set["set_hash"]
                    print(f"  determinism: {'IDENTICAL' if same else 'DIFFERENT'} "
                          f"(labels.jsonl bytes and set_hash)")
                    if not same:
                        rc = max(rc, 1)
                finally:
                    shutil.rmtree(second, ignore_errors=True)
            if args.validate:
                violations = validate_label_dir(result.label_dir, session_dir=session_dir)
                print(f"  validator: {'CLEAN' if not violations else f'{len(violations)} violations'}")
                for v in violations[:10]:
                    print(f"    - {v}")
                if violations:
                    rc = max(rc, 1)
        print(f"\nRESULT: {'PASS' if rc == 0 else 'FAIL'}")
        return rc
    finally:
        if tmp is not None and args.out == str(LABELS_ROOT):
            print(f"[selftest] temporary artefacts under {tmp} (removed)")
            shutil.rmtree(tmp, ignore_errors=True)
        elif tmp is not None:
            shutil.rmtree(tmp / "raw", ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
