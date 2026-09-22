"""Phase 07, Task 07.9 — label statistics report.

    python scripts/label_stats.py --all [--out docs/reports/phase-07-label-stats.md]
    python scripts/label_stats.py --selftest

Counts per class, zone, hand, segment type and participant; the ``intensity_proxy_gt``
distribution; reference-tracking validity around positives; the ambiguous and excluded fractions;
the review adjustment rate; distance and lighting strata sizes.

Statistics are grouped by ``source_kind`` and **never summed across kinds**: a SYNTHETIC table and
a PARTICIPANT table are two tables. The library raises rather than mixing them (integrity I-4).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import LABELS_ROOT, find_label_dirs, find_sessions, git_sha, use_utf8_stdout  # noqa: E402

from spacedrums.data.labels.generate import generate_labels, read_labels  # noqa: E402
from spacedrums.data.labels.schema import LABELS_FILENAME  # noqa: E402
from spacedrums.data.labels.stats import aggregate, markdown_table  # noqa: E402
from spacedrums.data.metadata import SessionMetadata  # noqa: E402


def session_strata(sessions: list[Path]) -> dict[str, dict[str, str]]:
    """Session-level descriptors used for the distance / lighting stratum sizes."""
    out: dict[str, dict[str, str]] = {}
    for sd in sessions:
        try:
            meta = SessionMetadata.read(sd)
        except (OSError, ValueError):  # pragma: no cover - unreadable session
            continue
        out[meta.session_id] = {
            "distance_mark": str(meta.data.get("distance_mark", {}).get("label", "UNKNOWN")),
            "lighting": str(meta.data.get("lighting", {}).get("condition", "UNKNOWN")),
        }
    return out


def report(labels: list[dict], strata: dict[str, dict[str, str]], *, title: str) -> str:
    groups = aggregate(labels, strata=strata)
    lines = [f"# {title}", ""]
    if not labels:
        lines += [
            "**PENDING — no labels exist.** No session has been labelled, because no participant "
            "session has been recorded (Phase 06 conditions C-06-1…C-06-4). Every count below "
            "would be a count of nothing and is therefore not reported.",
            "",
        ]
        return "\n".join(lines)
    participant = [k for k in groups if k in ("PILOT", "PARTICIPANT")]
    lines += [
        "Counts are MEASURED from the labels listed, grouped by evidence class. "
        "**Groups are never summed:** SYNTHETIC, DEV CAPTURE, PILOT and PARTICIPANT counts are "
        "separate tables and separate claims (integrity I-4).",
        "",
    ]
    if not participant:
        lines += [
            "> **No participant labels exist.** Every table below is SYNTHETIC or DEV CAPTURE "
            "material: generated observations and a developer recording. None of it is evidence "
            "about participants, about class balance in a real dataset, or about label quality. "
            "The participant tables are **PENDING** (Phase 06 conditions C-06-1…C-06-4).",
            "",
        ]
    lines += [
        "> **Review state.** No human has reviewed any label: every count is generator output with "
        "`qc_status = PENDING_REVIEW`, so the adjustment rate is reported as PENDING rather than "
        "as 0 (`docs/reports/phase-07-agreement.md`).",
        "",
        markdown_table(groups),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="statistics of a generated SYNTHETIC set")
    ap.add_argument("--labels-root", default=str(LABELS_ROOT))
    ap.add_argument("--out", default=None, help="write the markdown report to this path")
    args = ap.parse_args(argv)
    use_utf8_stdout()

    tmp = None
    try:
        if args.selftest:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "data"))
            from data_helpers import make_session

            tmp = Path(tempfile.mkdtemp(prefix="p07-stats-"))
            session_dir, _, _ = make_session(tmp / "raw", session_id="synthetic-p07-stats")
            result = generate_labels(session_dir, tmp / "labels",
                                     dataset_version="ds-v0.0-selftest-stats", git_sha=git_sha())
            labels = result.labels
            strata = session_strata([session_dir])
            title = "Phase 07 label statistics — SYNTHETIC self-test"
        else:
            dirs = find_label_dirs(Path(args.labels_root)) if args.all else [
                Path(p) for p in args.labels
            ]
            labels = [rec for d in dirs for rec in read_labels(d / LABELS_FILENAME)]
            strata = session_strata(find_sessions())
            title = "Phase 07 — Label Statistics"
        text = report(labels, strata, title=title)
        print(text)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
            print(f"\n[stats] wrote {args.out}")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
