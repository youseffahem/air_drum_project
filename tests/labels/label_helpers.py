"""Helpers for the Phase 07 label tests.

Builds a SYNTHETIC session on disk through the real Phase 05/06 record path (``tests/data``'s
``make_session``; ``tests/data`` is on ``pythonpath``) and labels it with the real generator, so
every test runs against artefacts the shipped code actually writes.

Kept in a uniquely named module rather than a ``conftest`` because ``from conftest import …`` is
order-fragile across test directories (tests/README.md).

**Nothing here is participant material.** Sessions are ``session_kind = SYNTHETIC`` with
``participant_id = SYNTHETIC`` and can only carry a ``ds-v0.0-selftest*`` dataset version; the
schemas and the manifest builder refuse anything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_helpers import make_session

from spacedrums.data.labels.generate import GenerateResult, generate_labels
from spacedrums.data.labels.rules import EventEvidence, Thresholds
from spacedrums.data.labels.schema import Interpolation
from spacedrums.data.labels.smooth import Measurement, ReferenceSmoother

SELFTEST_VERSION = "ds-v0.0-selftest-tests"
GIT = "c" * 40


def labelled_session(
    tmp_path: Path,
    *,
    session_id: str = "synthetic-labels",
    dataset_version: str = SELFTEST_VERSION,
    thresholds: Thresholds | None = None,
    smoother: ReferenceSmoother | None = None,
    interpolation: Interpolation | str = Interpolation.QUADRATIC,
    pad_zone: str | None = None,
    metadata_overrides: dict[str, Any] | None = None,
    write: bool = True,
) -> tuple[Path, GenerateResult, dict[str, Any]]:
    """(session_dir, generate result, extras) for a freshly recorded + labelled SYNTHETIC session."""
    session_dir, _, extra = make_session(
        tmp_path / "raw",
        session_id=session_id,
        pad_zone=pad_zone,
        metadata_overrides=metadata_overrides,
    )
    result = generate_labels(
        session_dir,
        tmp_path / "labels",
        dataset_version=dataset_version,
        thresholds=thresholds,
        smoother=smoother,
        interpolation=interpolation,
        git_sha=GIT,
        generated_at="2026-09-22T12:00:00+03:00",
        write=write,
    )
    return session_dir, result, extra


def evidence(**overrides: Any) -> EventEvidence:
    """A clean ENTRY evidence with a well-tracked window; override one field per rule test."""
    base = {
        "direction": "ENTRY",
        "inward_speed": 1.5,
        "min_distance": 0.0,
        "max_inward_speed": 1.5,
        "speed_at_min_distance": 1.5,
        "valid_fraction": 1.0,
        "mean_quality": 0.9,
        "interpolated": False,
        "in_quarantine": False,
        "recovery_of_entry": False,
    }
    base.update(overrides)
    return EventEvidence(**base)


def ramp(n: int = 40, dt: float = 1 / 30, t0: float = 100.0, y0: float = 0.2, vy: float = 1.0):
    """A straight constant-velocity descent: position and velocity are known in closed form."""
    return [Measurement(k, t0 + k * dt, (0.5, y0 + vy * k * dt), 0.9) for k in range(n)]


def parabola(n: int = 40, dt: float = 1 / 30, t0: float = 100.0, a: float = 4.0, t_min: float = 0.6):
    """A constant-acceleration descent/ascent with its minimum at ``t_min`` (seconds from t0)."""
    return [
        Measurement(k, t0 + k * dt, (0.5, 0.3 + 0.5 * a * (k * dt - t_min) ** 2), 0.9)
        for k in range(n)
    ]


__all__ = [
    "GIT",
    "SELFTEST_VERSION",
    "evidence",
    "labelled_session",
    "make_session",
    "parabola",
    "ramp",
]
