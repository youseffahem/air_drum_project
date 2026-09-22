"""Phase 07, Task 07.8 — build and (only when it is legitimate) freeze participant-level splits.

    python scripts/build_splits.py --dataset-version ds-v1.0 --freeze
    python scripts/build_splits.py --plan                 # print the rule table, no data needed
    python scripts/build_splits.py --selftest             # SYNTHETIC roster, leakage checks

The split rule ``P07-SPLIT-1`` (ADR-0021) is a function of the actual participant count ``P`` and
is fixed in code, so ``n_test`` and ``K`` cannot be chosen after seeing a result. The script
refuses to write a participant split while ``P = 0`` and refuses to freeze a self-test split at
all: ``data/splits/ds-v1.0/`` must not exist before the participants do.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import LABELS_ROOT, SPLITS_ROOT, find_label_dirs, use_utf8_stdout  # noqa: E402

from spacedrums.data.labels.generate import read_label_set  # noqa: E402
from spacedrums.data.labels.schema import LABEL_SET_FILENAME, LABELS_VERSION  # noqa: E402
from spacedrums.data.metadata import SessionKind  # noqa: E402
from spacedrums.data.splits import (  # noqa: E402
    NORMALISATION_RULE,
    SPLIT_RULE_ID,
    Roster,
    build_split,
    plan_for,
    roster_from_label_sets,
    write_split,
)


def print_plan() -> None:
    print(f"Split rule {SPLIT_RULE_ID} (ADR-0021) — n_test and K as a function of P:")
    print(f"{'P':>5} | {'n_test':>6} | {'K':>3} | note")
    print("-" * 100)
    for P in (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 25, 30):
        n_test, K, note = plan_for(P)
        print(f"{P:>5} | {n_test:>6} | {K:>3} | {note[:72]}")
    print()
    print(f"Normalisation rule carried into every split file: {NORMALISATION_RULE}")


def selftest() -> int:
    """Build a split from a SYNTHETIC roster and show that every guard fires."""
    roster = Roster(
        dataset_version="ds-v0.0-selftest-splits",
        labels_version=LABELS_VERSION,
        source_kind=SessionKind.SYNTHETIC,
        # SYNTHETIC pseudonyms: a machinery self-test, never a participant count.
        sessions_by_participant={f"SYNTHETIC-P{i:02d}": [f"SYNTHETIC-P{i:02d}-S1",
                                                         f"SYNTHETIC-P{i:02d}-S2"]
                                 for i in range(1, 11)},
    )
    test_doc, folds_doc = build_split(roster, seed=7)
    print(f"[selftest] SYNTHETIC roster P={roster.P} -> n_test={test_doc['n_test']} "
          f"K={folds_doc['K']} seed={test_doc['seed']}")
    print(f"[selftest] test participants: {test_doc['test_participants']}")
    print(f"[selftest] leakage checks: {test_doc['leakage_checks']}")
    print(f"[selftest] split_hash: {test_doc['split_hash']}")
    again, _ = build_split(roster, seed=7)
    print(f"[selftest] determinism: "
          f"{'IDENTICAL' if again['split_hash'] == test_doc['split_hash'] else 'DIFFERENT'}")
    ok = test_doc["leakage_checks"]["all_passed"] and again["split_hash"] == test_doc["split_hash"]
    for what, fn in (
        ("freezing a self-test split", lambda: build_split(roster, seed=7, freeze=True)),
        ("a SYNTHETIC roster claiming a participant dataset version",
         lambda: build_split(Roster("ds-v1.0", LABELS_VERSION, SessionKind.SYNTHETIC,
                                    roster.sessions_by_participant), seed=7)),
        ("writing an empty participant split",
         lambda: write_split(*build_split(Roster("ds-v1.0", LABELS_VERSION, SessionKind.PARTICIPANT,
                                                 {})), tempfile.mkdtemp())),
    ):
        try:
            fn()
            print(f"  NOT REFUSED {what}  <-- guard missing")
            ok = False
        except ValueError as exc:
            print(f"  REFUSED     {what}: {str(exc)[:90]}")
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset-version", default=None)
    ap.add_argument("--labels-version", default=LABELS_VERSION)
    ap.add_argument("--labels-root", default=str(LABELS_ROOT))
    ap.add_argument("--splits-root", default=str(SPLITS_ROOT))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--freeze", action="store_true", help="mark the split frozen (participants only)")
    ap.add_argument("--n-test", type=int, default=None, help="override the rule (records a deviation)")
    ap.add_argument("--k", type=int, default=None, help="override the rule (records a deviation)")
    ap.add_argument("--plan", action="store_true", help="print the rule table and exit")
    ap.add_argument("--source-kind", default=None,
                    choices=["SYNTHETIC", "DEV_CAPTURE", "PILOT", "PARTICIPANT"],
                    help="build the split for label sets of this kind only")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    use_utf8_stdout()

    if args.plan:
        print_plan()
        return 0
    if args.selftest:
        return selftest()
    if not args.dataset_version:
        ap.error("--dataset-version is required (or use --plan / --selftest)")

    dirs = find_label_dirs(Path(args.labels_root))
    label_sets = [read_label_set(d / LABEL_SET_FILENAME) for d in dirs]
    if args.source_kind:
        # A dataset is of one kind; when a development labels root holds several, the operator says
        # which one to build a split for rather than the tool guessing.
        label_sets = [s for s in label_sets if s["source_kind"] == args.source_kind]
    if not label_sets:
        n_test, K, note = plan_for(0)
        print("[splits] no label set exists — no participant split can be built.")
        print(f"[splits] rule {SPLIT_RULE_ID} at P = 0: n_test = {n_test}, K = {K} ({note})")
        print("RESULT: PENDING (participant data required)")
        return 0
    try:
        roster = roster_from_label_sets(label_sets, dataset_version=args.dataset_version,
                                        labels_version=args.labels_version)
        test_doc, folds_doc = build_split(roster, seed=args.seed, freeze=args.freeze,
                                          n_test=args.n_test, K=args.k)
        a, b = write_split(test_doc, folds_doc, Path(args.splits_root))
    except ValueError as exc:
        print(f"[refused] {exc}")
        return 2
    print(f"[splits] P = {test_doc['P']} n_test = {test_doc['n_test']} K = {folds_doc['K']} "
          f"frozen = {test_doc['frozen']}")
    print(f"[splits] leakage checks: {json.dumps(test_doc['leakage_checks'])}")
    print(f"[splits] wrote {a} and {b}")
    print(f"RESULT: {'PASS' if test_doc['leakage_checks']['all_passed'] else 'FAIL'}")
    return 0 if test_doc["leakage_checks"]["all_passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
