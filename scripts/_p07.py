"""Shared helper for the Phase 07 scripts (labelling, QC, splits, dataset manifest).

Holds what every Phase 07 script needs and nothing else: the repository paths, the common
command-line options (dataset version, labels version, thresholds, smoother, interpolation), git
provenance, and the discovery of session directories under ``data/raw/``.

The same refusal that guards Phase 06 manifests guards every entry point here: a SYNTHETIC or DEV
CAPTURE session can only produce a ``ds-v0.0-selftest*`` dataset version, and a participant dataset
version cannot be written while no participant session exists. The refusal is in the library
(``spacedrums.data.labels.schema.admissible_source``); the scripts only surface it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from spacedrums.data.labels.rules import Thresholds  # noqa: E402
from spacedrums.data.labels.schema import (  # noqa: E402
    LABEL_SET_FILENAME,
    LABELS_DIRNAME,
    LABELS_VERSION,
    Interpolation,
    SmootherId,
    dataset_kind,
)
from spacedrums.data.labels.smooth import ReferenceSmoother  # noqa: E402
from spacedrums.data.metadata import METADATA_FILENAME  # noqa: E402

RAW_ROOT = ROOT / "data" / "raw"
LABELS_ROOT = ROOT / "data" / LABELS_DIRNAME
MANIFESTS_DIR = ROOT / "data" / "manifests"
SPLITS_ROOT = ROOT / "data" / "splits"
DOCS_DATASET = ROOT / "docs" / "dataset"
SELFTEST_VERSION = "ds-v0.0-selftest"


def use_utf8_stdout() -> None:
    """Print UTF-8 regardless of the console code page (the reports contain em dashes)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):  # pragma: no cover - already wrapped or not a tty
            pass


def add_common_options(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--dataset-version",
        default=SELFTEST_VERSION,
        help="ds-v<M>.<m> (participant), ds-v<M>.<m>-pilot, or ds-v0.0-selftest[-<slug>] "
        "(SYNTHETIC / DEV CAPTURE only). Default: the self-test version.",
    )
    ap.add_argument("--labels-version", default=LABELS_VERSION)
    ap.add_argument(
        "--smoother",
        default=str(SmootherId.RTS_KALMAN_CV),
        choices=[str(s) for s in SmootherId],
        help="Non-causal reference smoother (Task 07.2; the choice is a candidate pending "
        "validation against manual tip annotations).",
    )
    ap.add_argument("--max-gap-s", type=float, default=0.20,
                    help="Reference-smoother bridging bound; longer gaps become NEG_TRACKING_LOSS.")
    ap.add_argument(
        "--interpolation",
        default=str(Interpolation.QUADRATIC),
        choices=[str(i) for i in Interpolation],
        help="Sub-frame crossing estimator for t_impact_est "
        "(ADR-0020 chose QUADRATIC on SYNTHETIC evidence).",
    )
    ap.add_argument("--thresholds", default=None,
                    help="JSON object overriding individual rules.Thresholds fields (candidates).")


def thresholds_from_args(args: argparse.Namespace) -> Thresholds:
    if not getattr(args, "thresholds", None):
        return Thresholds()
    import json

    return Thresholds.from_dict(json.loads(args.thresholds))


def smoother_from_args(args: argparse.Namespace) -> ReferenceSmoother:
    return ReferenceSmoother(args.smoother, max_gap_s=args.max_gap_s)


def check_dataset_version(dataset_version: str) -> str:
    """Return the manifest kind, raising with a readable message on an unknown pattern."""
    return dataset_kind(dataset_version)


def find_sessions(raw_root: Path | None = None, patterns: list[str] | None = None) -> list[Path]:
    """Session directories under ``data/raw/<participant>/<session>/`` that carry metadata."""
    root = raw_root or RAW_ROOT
    if not root.exists():
        return []
    dirs = sorted(p for p in root.glob("*/*") if p.is_dir() and (p / METADATA_FILENAME).exists())
    if patterns:
        dirs = [d for d in dirs if any(pat in d.as_posix() for pat in patterns)]
    return dirs


def find_label_dirs(labels_root: Path | None = None) -> list[Path]:
    root = labels_root or LABELS_ROOT
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*") if p.is_dir() and (p / LABEL_SET_FILENAME).exists())


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git in the environment
        return "0" * 40


def git_dirty() -> bool:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return True
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if path.startswith(("data/", "experiments/", ".venv/")):
            continue
        return True
    return False


__all__ = [
    "DOCS_DATASET",
    "LABELS_ROOT",
    "MANIFESTS_DIR",
    "RAW_ROOT",
    "ROOT",
    "SELFTEST_VERSION",
    "SPLITS_ROOT",
    "add_common_options",
    "check_dataset_version",
    "find_label_dirs",
    "find_sessions",
    "git_dirty",
    "git_sha",
    "smoother_from_args",
    "thresholds_from_args",
    "use_utf8_stdout",
]
