"""Phase 07, Task 07.10 — labelled-dataset manifest (``ds-v*``) and dataset card.

    python scripts/build_dataset_manifest.py build ds-v1.0 [--raw-manifest data/manifests/ds-raw-v1.0.json]
    python scripts/build_dataset_manifest.py check data/manifests/ds-v1.0.json
    python scripts/build_dataset_manifest.py card ds-v1.0 --out docs/dataset/dataset-card-ds-v1.0.md
    python scripts/build_dataset_manifest.py selftest

Admission is kind-gated (participant / pilot / self-test), every listed label set must share the
dataset's ``labels_hash``, and an empty participant manifest is refused: ``ds-v1.0.json`` must not
exist before participant label sets do. Refused sets are listed with their reason; nothing is
re-labelled (integrity I-4).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import (  # noqa: E402
    DOCS_DATASET,
    LABELS_ROOT,
    MANIFESTS_DIR,
    find_label_dirs,
    git_dirty,
    git_sha,
    use_utf8_stdout,
)

from spacedrums.data.labels.dataset import (  # noqa: E402
    build_manifest,
    check_manifest_files,
    dataset_card,
    phys_summary,
    read_manifest,
    write_manifest,
)
from spacedrums.data.labels.generate import generate_labels, read_label_set, read_labels  # noqa: E402
from spacedrums.data.labels.schema import LABEL_SET_FILENAME, LABELS_FILENAME  # noqa: E402


def _cmd_build(args: argparse.Namespace) -> int:
    raw = None
    if args.raw_manifest and Path(args.raw_manifest).exists():
        raw = json.loads(Path(args.raw_manifest).read_text(encoding="utf-8"))
    try:
        doc = build_manifest(
            Path(args.labels_root),
            args.dataset_version,
            raw_manifest=raw,
            raw_manifest_path=args.raw_manifest,
            git_sha=git_sha(),
            git_dirty=git_dirty(),
            notes=args.notes,
        )
        path = write_manifest(doc, Path(args.manifests_dir), allow_empty=args.allow_empty)
    except ValueError as exc:
        print(f"[refused] {exc}")
        return 2
    print(f"[manifest] {doc['dataset_version']} ({doc['kind']}): "
          f"{doc['totals']['n_label_sets']} label sets, {doc['totals']['n_labels']} labels, "
          f"{doc['totals']['n_participants']} participants")
    for r in doc["refused"]:
        print(f"  refused {r['session_id']}: {r['reason']}")
    print(f"[manifest] wrote {path}")
    print(f"[manifest] manifest_hash {doc['manifest_hash']}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    doc = read_manifest(args.path)
    problems = check_manifest_files(doc, Path(args.labels_root))
    print(f"[check] {doc['dataset_version']}: {len(doc['label_sets'])} label sets, "
          f"{len(problems)} problems")
    for p in problems[:20]:
        print(f"  - {p}")
    print(f"RESULT: {'PASS' if not problems else 'FAIL'}")
    return 0 if not problems else 1


def _cmd_card(args: argparse.Namespace) -> int:
    path = Path(args.manifests_dir) / f"{args.dataset_version}.json"
    if args.pending:
        # The card of a dataset that does not exist yet: built from an in-memory manifest with no
        # label set, so every count-bearing section renders as PENDING. No manifest is written -
        # ds-v1.0.json must not exist before participant label sets do.
        doc = build_manifest(Path(args.labels_root), args.dataset_version, git_sha=git_sha(),
                             git_dirty=git_dirty(), label_dirs=[])
        text = dataset_card(doc)
    elif not path.exists():
        print(f"[card] no manifest {path} — build it first, or use --pending for the PENDING card")
        return 2
    else:
        doc = read_manifest(path)
        dirs = find_label_dirs(Path(args.labels_root))
        labels = [rec for d in dirs for rec in read_labels(d / LABELS_FILENAME)]
        sets = [read_label_set(d / LABEL_SET_FILENAME) for d in dirs]
        text = dataset_card(doc, labels=labels, phys=phys_summary(sets) if sets else None)
    out = Path(args.out or DOCS_DATASET / f"dataset-card-{args.dataset_version}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"[card] wrote {out} ({len(text.splitlines())} lines)")
    return 0


def _cmd_selftest(_: argparse.Namespace) -> int:
    """Build a self-test dataset from one SYNTHETIC session and show that the guards fire."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "data"))
    from data_helpers import make_session

    tmp = Path(tempfile.mkdtemp(prefix="p07-manifest-"))
    ok = True
    try:
        session_dir, _, _ = make_session(tmp / "raw", session_id="synthetic-p07-manifest")
        generate_labels(session_dir, tmp / "labels",
                        dataset_version="ds-v0.0-selftest-manifest", git_sha=git_sha())
        doc = build_manifest(tmp / "labels", "ds-v0.0-selftest-manifest", git_sha=git_sha())
        path = write_manifest(doc, tmp / "manifests")
        print(f"[selftest] {doc['dataset_version']}: {doc['totals']['n_label_sets']} sets, "
              f"{doc['totals']['n_labels']} labels, hash {doc['manifest_hash'][:23]}...")
        problems = check_manifest_files(doc, tmp / "labels")
        print(f"[selftest] file re-hash: {'MATCH' if not problems else problems[:2]}")
        ok = ok and not problems
        again = build_manifest(tmp / "labels", "ds-v0.0-selftest-manifest", git_sha=git_sha())
        print(f"[selftest] determinism: "
              f"{'IDENTICAL' if again['manifest_hash'] == doc['manifest_hash'] else 'DIFFERENT'}")
        ok = ok and again["manifest_hash"] == doc["manifest_hash"]
        participant = build_manifest(tmp / "labels", "ds-v1.0", git_sha=git_sha())
        print(f"[selftest] SYNTHETIC set offered to ds-v1.0: refused with "
              f"{[r['reason'][:60] for r in participant['refused']]}")
        ok = ok and participant["totals"]["n_label_sets"] == 0 and participant["refused"]
        try:
            write_manifest(participant, tmp / "manifests")
            print("  NOT REFUSED writing an empty participant manifest  <-- guard missing")
            ok = False
        except ValueError as exc:
            print(f"  REFUSED     writing an empty participant manifest: {str(exc)[:80]}")
        sets = [read_label_set(d / LABEL_SET_FILENAME) for d in find_label_dirs(tmp / "labels")]
        card = dataset_card(read_manifest(path),
                            labels=[rec for d in find_label_dirs(tmp / "labels")
                                    for rec in read_labels(d / LABELS_FILENAME)],
                            phys=phys_summary(sets))
        print(f"[selftest] dataset card rendered: {len(card.splitlines())} lines; "
              f"PENDING sections: {card.count('PENDING')}")
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels-root", default=str(LABELS_ROOT))
    ap.add_argument("--manifests-dir", default=str(MANIFESTS_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("dataset_version")
    b.add_argument("--raw-manifest", default=None)
    b.add_argument("--allow-empty", action="store_true")
    b.add_argument("--notes", default="")
    b.set_defaults(fn=_cmd_build)
    c = sub.add_parser("check")
    c.add_argument("path")
    c.set_defaults(fn=_cmd_check)
    d = sub.add_parser("card")
    d.add_argument("dataset_version")
    d.add_argument("--out", default=None)
    d.add_argument("--pending", action="store_true",
                   help="render the card of a dataset that does not exist yet (every count PENDING)")
    d.set_defaults(fn=_cmd_card)
    s = sub.add_parser("selftest")
    s.set_defaults(fn=_cmd_selftest)
    args = ap.parse_args(argv)
    use_utf8_stdout()
    return int(args.fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
