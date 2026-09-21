"""Phase 06, Task 06.7 — post-session verification and the unusable-recording policy (Task 06.8).

    python scripts/verify_session.py <session_dir> [<session_dir> ...] [--thresholds file.yaml]
        [--exclusions-log data/raw/exclusions.jsonl] [--json]

Runs ``spacedrums.data.validation.verify_session`` on each directory, writes ``<session_dir>/verify.json``
(schema ``session-verification``), prints the verdict ``ACCEPT | REVIEW | QUARANTINE`` with reasons and
the quality report, and appends the produced ``ExclusionRecord``s to the exclusions log if one is
given. Exit code 0 for ACCEPT / REVIEW, 2 if any session is QUARANTINE, 1 on error.

Every threshold is a candidate (``VerifyThresholds``); the values used are written into the document
with their hash. The verdict of a SYNTHETIC or DEV CAPTURE session is machinery evidence only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import git_sha  # noqa: E402

from spacedrums.data.validation import (  # noqa: E402
    VerifyThresholds,
    format_verdict,
    validate_verification,
    verify_session,
    write_exclusions,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_dirs", nargs="+", type=Path)
    ap.add_argument("--thresholds", type=Path, default=None, help="YAML with VerifyThresholds overrides")
    ap.add_argument("--exclusions-log", type=Path, default=None, help="append ExclusionRecords here (JSONL)")
    ap.add_argument("--schema-sample", type=int, default=None, help="validate only ~N records per stream")
    ap.add_argument("--no-write", action="store_true", help="do not write verify.json")
    ap.add_argument("--json", action="store_true", help="print the full document instead of the summary")
    args = ap.parse_args(argv)
    th = VerifyThresholds.from_file(args.thresholds) if args.thresholds else VerifyThresholds()
    if args.schema_sample is not None:
        th = VerifyThresholds(**{**th.to_dict(), "schema_sample": args.schema_sample})
    worst = 0
    sha = git_sha()
    for sd in args.session_dirs:
        if not sd.is_dir():
            print(f"ERROR: {sd} is not a directory")
            return 1
        doc = verify_session(sd, thresholds=th, write=not args.no_write, git_sha=sha)
        errs = validate_verification(doc)
        if errs:
            print(f"ERROR: verify document invalid: {errs[0]}")
            return 1
        print(json.dumps(doc, indent=2) if args.json else format_verdict(doc))
        if args.exclusions_log and doc["exclusions"]:
            write_exclusions(args.exclusions_log, doc["exclusions"])
            print(f"  {len(doc['exclusions'])} exclusion record(s) appended to {args.exclusions_log}")
        if doc["verdict"] == "QUARANTINE":
            worst = 2
    return worst


if __name__ == "__main__":
    sys.exit(main())
