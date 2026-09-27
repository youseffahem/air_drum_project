"""``ReplayFrameSource`` — the basic replay source of architecture.md section 12 (Phase 05, Task 05.5).

Reads a recorded session directory (the app's record mode, or a Phase 02/03 dev capture — both are
``frames.jsonl`` with one ``FrameSample`` per line whose ``image_ref`` is ``FILE`` + a lossless PNG
per frame) and yields ``FrameSample``s **in ``frame_id`` order with the original ``t_capture`` /
``t_frame_available`` / ``dropped_since_last``** and ``timestamp_source = REPLAY``
(``TEST-CONFORM-7``). The processing loop cannot tell it from ``LiveFrameSource``; processing-done
stamps are re-stamped live, decisions must be identical (informal replay check here, formal
``TEST-PARITY-1`` in Phase 13).

This promotes the Phase 03 script helper ``scripts/_devcapture.py`` into the package, as that helper
announced; the script helper stays for the Phase 03 scripts and is not a third implementation of the
format (the format is the same).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spacedrums.capture.roi import Roi, crop_roi
from spacedrums.contracts import FrameSample, FrameView, ImageRef, TimestampSource


class ReplayFrameSource:
    """Replay ``FrameSource`` over ``<session_dir>/frames.jsonl`` + FILE image refs."""

    def __init__(self, session_dir: str | Path, *, limit: int | None = None) -> None:
        self.dir = Path(session_dir)
        frames = self.dir / "frames.jsonl"
        if not frames.exists():
            raise FileNotFoundError(f"{self.dir} has no frames.jsonl")
        self.meta: dict[str, Any] = {}
        for name in ("session.json", "meta.json"):
            if (self.dir / name).exists():
                self.meta = json.loads((self.dir / name).read_text(encoding="utf-8"))
                break
        samples: list[FrameSample] = []
        last_id = -1
        with frames.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = FrameSample.from_dict(json.loads(line))
                if rec.frame_id <= last_id:
                    raise ValueError(f"{frames}: frame_id {rec.frame_id} not strictly increasing")
                # Phase 17: a broken timestamp stream is refused here, never mid-run in the pipeline
                if samples and rec.t_capture <= samples[-1].t_capture:
                    raise ValueError(f"{frames}: t_capture of frame {rec.frame_id} not strictly increasing")
                if rec.image_ref.path is None:
                    raise ValueError(f"{frames}: frame {rec.frame_id} has no FILE image_ref")
                last_id = rec.frame_id
                samples.append(FrameSample(**{**rec.__dict__, "timestamp_source": TimestampSource.REPLAY}))
                if limit is not None and len(samples) >= limit:
                    break
        self.samples: tuple[FrameSample, ...] = tuple(samples)
        self._roi = Roi.from_rect(self.samples[0].roi_px) if self.samples else None

    def __len__(self) -> int:
        return len(self.samples)

    def __iter__(self) -> Iterator[FrameSample]:
        yield from self.samples

    @property
    def roi(self) -> Roi | None:
        return self._roi

    def read_image(self, sample: FrameSample) -> np.ndarray:
        assert sample.image_ref.path is not None
        img = cv2.imread(str(self.dir / sample.image_ref.path), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"cannot read {self.dir / sample.image_ref.path}")
        return img

    def view(self, sample: FrameSample) -> FrameView:
        """``FrameView`` with the ROI as a pure slice; ``full`` is None for ROI-only recordings."""
        img = self.read_image(sample)
        roi = Roi.from_rect(sample.roi_px)
        if sample.image_ref.crop is not None and str(sample.image_ref.crop) == "ROI":
            return FrameView(sample=sample, roi=img, full=None)
        return FrameView(sample=sample, roi=crop_roi(img, roi), full=img)

    def views(self) -> Iterator[FrameView]:
        for s in self.samples:
            yield self.view(s)

    @staticmethod
    def memory_sample(sample: FrameSample, image: np.ndarray) -> FrameSample:
        """Same record with an in-memory image (for stages that want ``image_ref.array``)."""
        return FrameSample(**{**sample.__dict__, "image_ref": ImageRef.memory(image)})


__all__ = ["ReplayFrameSource"]
