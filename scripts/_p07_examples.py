"""Regenerate the Phase 07 schema examples under ``schemas/examples/`` (labelled SYNTHETIC).

    python scripts/_p07_examples.py

The examples are **synthetic placeholders, not data** (``docs/architecture/contracts.md`` §1). They
are produced by the real generator, review tool, split builder and manifest builder on a generated
SYNTHETIC session, so an example can never drift away from what the code actually writes: if a
producer changes, this script is re-run and the diff shows the contract change.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "schemas" / "examples"

from spacedrums.data.labels.dataset import build_manifest  # noqa: E402
from spacedrums.data.labels.generate import generate_labels  # noqa: E402
from spacedrums.data.labels.review import make_entry  # noqa: E402
from spacedrums.data.labels.schema import (  # noqa: E402
    LABEL_SET_FILENAME,
    REFERENCE_TRACK_FILENAME,
    LabelClass,
    ReviewDecision,
    label_set_hash,
)
from spacedrums.data.metadata import SessionKind  # noqa: E402
from spacedrums.data.splits import Roster, build_split  # noqa: E402

GIT = "0" * 40
STAMP = "2026-09-22T12:00:00+03:00"


def write(name: str, doc: object) -> Path:
    path = EXAMPLES / f"{name}.valid.example.json"
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(f"[examples] wrote {path.relative_to(ROOT).as_posix()}")
    return path


def main() -> int:
    sys.path.insert(0, str(ROOT / "tests" / "data"))
    from data_helpers import make_session

    tmp = Path(tempfile.mkdtemp(prefix="p07-examples-"))
    try:
        session_dir, _, _ = make_session(tmp / "raw", session_id="synthetic-example")
        result = generate_labels(session_dir, tmp / "labels",
                                 dataset_version="ds-v0.0-selftest-example", git_sha=GIT,
                                 generated_at=STAMP)
        positive = next(
            (r for r in result.labels if r["label_class"] == str(LabelClass.POSITIVE)),
            result.labels[0],
        )
        write("label-record", positive)

        header = json.loads(
            (result.label_dir / REFERENCE_TRACK_FILENAME).read_text(encoding="utf-8").splitlines()[0]
        )
        write("reference-track", header)

        # The session lives in a temporary directory; the example records the repository-relative
        # path it would have in a real run, so the committed example is reproducible. The
        # normalised document is written back to disk first, because the dataset manifest below
        # lists its set_hash.
        label_set = json.loads((result.label_dir / LABEL_SET_FILENAME).read_text(encoding="utf-8"))
        label_set["generated_at"] = STAMP
        label_set["inputs"]["session_dir"] = "data/raw/SYNTHETIC/synthetic-example"
        label_set["set_hash"] = label_set_hash(label_set)
        (result.label_dir / LABEL_SET_FILENAME).write_text(
            json.dumps(label_set, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        write("label-set", label_set)

        entry = make_entry(
            positive,
            decision=ReviewDecision.ADJUST,
            reviewer_id="A1",
            reviewed_at=STAMP,
            pass_no=1,
            after={
                "t_impact_est": positive["t_impact_est"],
                "t_event": positive["t_event"],
                "zone_id": positive["zone_id"],
                "label_class": positive["label_class"],
            },
            reason="sub-frame adjustment after scrubbing",
            notes="example entry",
        )
        write("label-review", entry)

        roster = Roster(
            dataset_version="ds-v0.0-selftest-example",
            labels_version=positive["labels_version"],
            source_kind=SessionKind.SYNTHETIC,
            sessions_by_participant={f"SYNTHETIC-P{i:02d}": [f"SYNTHETIC-P{i:02d}-S1"]
                                     for i in range(1, 7)},
        )
        _, folds = build_split(roster, seed=0)
        write("split-file", folds)

        manifest = build_manifest(tmp / "labels", "ds-v0.0-selftest-example", git_sha=GIT,
                                  git_dirty=False, generated_at=STAMP)
        manifest["root"] = "data/labels"
        for s in manifest["label_sets"]:
            s["path"] = "synthetic-example"
        from spacedrums.data.labels.dataset import manifest_hash

        manifest["manifest_hash"] = manifest_hash(manifest)
        write("dataset-manifest", manifest)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
