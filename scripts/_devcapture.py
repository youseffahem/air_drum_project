"""Replay a developer-only dev capture (``data/dev-captures/<name>/``) as ``FrameSample`` + ``FrameView``.

Phase 02's ``exposure_blur_check.py record`` writes a lossless PNG sequence plus ``frames.jsonl``
(one ``FrameSample`` per line with ``image_ref = FILE``) and ``meta.json``. This helper reads that
back for the Phase 03 measurement scripts: every ``t_capture`` is reproduced **exactly** as recorded
and ``timestamp_source`` is set to ``REPLAY`` (``TEST-CONFORM-7`` rule for a replay source).

Scope note: this is a *script helper* for dev captures (like ``_runlog.py``). The full
``ReplayFrameSource`` of architecture.md section 12 (video containers, record-stream headers,
regenerated records) belongs to ``spacedrums.capture`` and is built by Phases 09/13; it must not be
re-implemented a third time — promote this reader then.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spacedrums.capture import Roi, crop_roi
from spacedrums.contracts import FrameSample, FrameView, ImageRef, TimestampSource

ROOT = Path(__file__).resolve().parents[1]
DEV_CAPTURES = ROOT / "data" / "dev-captures"


@dataclass(frozen=True)
class DevCapture:
    name: str
    dir: Path
    meta: dict[str, Any]
    samples: tuple[FrameSample, ...]

    @property
    def roi(self) -> Roi:
        return Roi.from_rect(self.meta["roi_px"])

    def __len__(self) -> int:
        return len(self.samples)


def load_dev_capture(name: str, *, limit: int | None = None) -> DevCapture:
    d = DEV_CAPTURES / name
    if not (d / "frames.jsonl").exists():
        raise FileNotFoundError(f"dev capture {name!r} has no frames.jsonl under {d}")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    samples: list[FrameSample] = []
    with (d / "frames.jsonl").open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = FrameSample.from_dict(json.loads(line))
            # Replay: same frame_id, same t_capture / t_frame_available, REPLAY label, FILE ref kept.
            samples.append(FrameSample(**{**rec.__dict__, "timestamp_source": TimestampSource.REPLAY}))
            if limit is not None and len(samples) >= limit:
                break
    return DevCapture(name=name, dir=d, meta=meta, samples=tuple(samples))


def read_frame(cap: DevCapture, sample: FrameSample) -> np.ndarray:
    ref: ImageRef = sample.image_ref
    if ref.path is None:
        raise ValueError("dev-capture sample has no FILE image_ref")
    img = cv2.imread(str(cap.dir / ref.path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"cannot read {cap.dir / ref.path}")
    return img


def iter_views(cap: DevCapture) -> Iterator[FrameView]:
    """``FrameView`` per recorded frame, in ``frame_id`` order, ROI as a pure slice of the full frame."""
    roi = cap.roi
    for s in cap.samples:
        full = read_frame(cap, s)
        yield FrameView(sample=s, roi=crop_roi(full, roi), full=full)


def list_dev_captures() -> list[str]:
    if not DEV_CAPTURES.exists():
        return []
    return sorted(p.name for p in DEV_CAPTURES.iterdir() if (p / "frames.jsonl").exists())


__all__ = ["DEV_CAPTURES", "DevCapture", "iter_views", "list_dev_captures", "load_dev_capture", "read_frame"]
