"""Phase 18 Task 18.1: archive, verify and approve the pre-registration by its hash.

    python scripts/prereg_archive.py archive --note "<why this version>" [--after-lock-reason "<why>"]
    python scripts/prereg_archive.py verify [--cite docs/reports/phase-18-final-evaluation.md ...]
    python scripts/prereg_archive.py approve --by "<owner / supervisor>" --date YYYY-MM-DD [--note ...]

* ``archive`` appends the current digest of ``docs/experiments/phase-18-prereg.md`` to
  ``docs/experiments/phase-18-prereg.hashes.json``, with timestamp, HEAD and dirty state. It does
  nothing if the digest is unchanged.
  - A new version after a lock was archived against the previous one is a **new pre-registered
    run**, and needs ``--after-lock-reason``.
* ``verify`` exits 1 unless the document matches its latest archived version. With ``--cite``,
  every listed report must quote that version's digest ("pre-registration hash verified in the
  report").
* ``approve`` records an owner or supervisor approval against the latest archived version
  (gate procedure §1). The approver runs it; an agent never runs it on their behalf.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p18 import PREREG_DOC, PREREG_PATH, RECORD_PATH, ROOT  # noqa: E402
from _runlog import git_dirty, git_sha  # noqa: E402

from spacedrums.live_eval.prereg import (  # noqa: E402
    PreregError,
    archive_document,
    latest_version,
    read_record,
    verify_document,
    write_record,
)
from spacedrums.timing import wall_clock_iso  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("archive")
    a.add_argument("--note", required=True)
    a.add_argument("--after-lock-reason", default=None)
    v = sub.add_parser("verify")
    v.add_argument("--cite", type=Path, action="append", default=[])
    p = sub.add_parser("approve")
    p.add_argument("--by", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--note", default="")
    args = ap.parse_args(argv)
    if args.command == "archive":
        try:
            entry = archive_document(
                PREREG_PATH,
                RECORD_PATH,
                document=PREREG_DOC,
                archived_at=wall_clock_iso(),
                git_head=git_sha(),
                git_dirty=git_dirty(),
                note=args.note,
                after_lock_reason=args.after_lock_reason,
            )
        except PreregError as exc:
            print(f"[prereg] refused: {exc}")
            return 2
        print(json.dumps(entry, indent=2))
        return 0
    check = verify_document(PREREG_PATH, RECORD_PATH, document=PREREG_DOC)
    if args.command == "approve":
        if not check["ok"]:
            print(f"[prereg] refused: {check['reason']}")
            return 2
        record = read_record(RECORD_PATH, PREREG_DOC)
        record["approvals"].append(
            {
                "version": latest_version(record)["version"],
                "sha256": check["sha256"],
                "by": args.by,
                "date": args.date,
                "note": args.note,
                "recorded_at": wall_clock_iso(),
            }
        )
        write_record(RECORD_PATH, record)
        print(f"[prereg] approval recorded for version {check['version']}")
        return 0
    problems = [] if check["ok"] else [check["reason"]]
    for report in args.cite:
        text = (
            (ROOT / report).read_text(encoding="utf-8")
            if not report.is_absolute()
            else report.read_text(encoding="utf-8")
        )
        if check.get("sha256") and check["sha256"] not in text:
            problems.append(f"{report} does not quote the archived digest {check.get('sha256')}")
    print(json.dumps({**check, "cited_reports": [str(c) for c in args.cite], "problems": problems}, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
