"""Phase 06, Task 06.9 — build, check or amend a raw-dataset manifest.

    python scripts/build_raw_manifest.py build ds-raw-v1.0 [--raw-root data/raw]
        [--manifests-dir data/manifests] [--include-review] [--notes "..."]
    python scripts/build_raw_manifest.py check data/manifests/ds-raw-v1.0.json [--raw-root data/raw]
    python scripts/build_raw_manifest.py withdraw data/manifests/ds-raw-v1.0.json
        --participant P07 --date YYYY-MM-DD

``build`` lists every verified, accepted session under ``<raw_root>/<participant>/<session>/`` whose
kind matches the version (participant ``ds-raw-v<M>.<m>``, pilot ``…-pilot``, self-test
``ds-raw-v0.0-selftest[-<slug>]`` for SYNTHETIC / DEV CAPTURE sessions only), with SHA-256 per file,
and writes ``<manifests_dir>/<version>.json`` + ``<version>.exclusions.jsonl``. Sessions it refuses
(wrong kind, consent not SIGNED, QUARANTINE / unverified) are listed in the manifest's ``refused``
block. ``check`` re-hashes every listed file. ``withdraw`` removes a participant's sessions and adds a
withdrawal record (the files themselves are deleted by the owner; Task 06.8).

No manifest for participant data can exist before participants were recorded: the only manifests
producible today are self-test manifests, labelled TEST / DEVELOPMENT ONLY.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p06 import MANIFESTS_DIR, RAW_ROOT, git_dirty, git_sha  # noqa: E402

from spacedrums.data.manifest import (  # noqa: E402
    apply_withdrawal,
    build_raw_manifest,
    check_manifest_files,
    read_manifest,
    write_manifest,
)


def cmd_build(args: argparse.Namespace) -> int:
    doc = build_raw_manifest(
        args.raw_root,
        args.dataset_version,
        include_review=args.include_review,
        git_sha=git_sha(),
        git_dirty=git_dirty(),
        notes=args.notes,
    )
    if doc["kind"] in ("PARTICIPANT", "PILOT") and not doc["sessions"]:
        print(
            f"[manifest] {doc['dataset_version']} [{doc['kind']}]: no accepted session of that kind "
            "- NOT written"
        )
        for r in doc["refused"]:
            print(f"  - refused {r['session_id']}: {r['reason']}")
        return 3
    mpath, epath = write_manifest(doc, args.manifests_dir)
    t = doc["totals"]
    print(f"[manifest] {doc['dataset_version']} [{doc['kind']}] :: {doc['label']}")
    print(
        f"[manifest] {t['n_sessions']} sessions, {t['n_participants']} participant ids, "
        f"{t['n_files']} files, "
        f"{t['total_bytes']} bytes, {t['total_duration_s']:.1f} s of frames ({t['label']})"
    )
    for s in doc["sessions"]:
        print(
            f"  + {s['participant_id']}/{s['session_id']} [{s['session_kind']}] {s['verdict']} "
            f"{s['n_files']} files"
        )
    for r in doc["refused"]:
        print(f"  - refused {r['session_id']}: {r['reason']}")
    print(f"[manifest] wrote {mpath} (manifest_hash {doc['manifest_hash']}) and {epath}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    doc = read_manifest(args.manifest)
    problems = check_manifest_files(doc, args.raw_root)
    print(f"[manifest] {doc['dataset_version']}: {len(doc['sessions'])} sessions; {len(problems)} problems")
    for p in problems[:50]:
        print("  " + p)
    return 2 if problems else 0


def cmd_withdraw(args: argparse.Namespace) -> int:
    doc = read_manifest(args.manifest)
    out = apply_withdrawal(doc, args.participant, date=args.date, note=args.note)
    mpath, _ = write_manifest(out, Path(args.manifest).parent)
    print(
        f"[manifest] {args.participant} withdrawn: {out['withdrawals'][-1]['n_sessions_removed']} "
        "session(s) removed; "
        f"rewrote {mpath}. Delete the participant's files under the raw root (owner action; Task 06.8)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("dataset_version")
    b.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    b.add_argument("--manifests-dir", type=Path, default=MANIFESTS_DIR)
    b.add_argument("--include-review", action="store_true", help="also list sessions with verdict REVIEW")
    b.add_argument("--notes", default="")
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check")
    c.add_argument("manifest", type=Path)
    c.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    c.set_defaults(fn=cmd_check)
    w = sub.add_parser("withdraw")
    w.add_argument("manifest", type=Path)
    w.add_argument("--participant", required=True)
    w.add_argument("--date", required=True)
    w.add_argument("--note", default="")
    w.set_defaults(fn=cmd_withdraw)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
