"""Record mode (Phase 05, Task 05.5; architecture.md section 12.2; Phase 01 Task 01.9).

Persists, under ``<output_dir>/<session_id>/``:

    frames/frame_NNNNNN.png      every delivered frame, lossless PNG (FULL or ROI crop per config) — raw
    frames.jsonl                 one FrameSample per frame with image_ref = FILE               — raw
    records/<RecordType>.jsonl   header line + one record per line, every record type produced — derived
    timing.jsonl                 TimingRecords (FRAME and STRIKE)                              — derived
    config.snapshot.yaml         the resolved config in force (+ config_hash)                   — provenance
    session.json                 Phase 05 session provenance (NOT the Phase 06 SessionMetadata) — provenance

A stream is written even when empty (header only). Dropped frames are not recorded (nothing to
record) but their count travels in ``dropped_since_last``. PNG is lossless, so regeneration from the
recording is exact; the Phase 06 codec decision does not apply to Phase 05 developer sessions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spacedrums.app.pipeline import HANDS, FrameResult
from spacedrums.capture import Roi, crop_roi
from spacedrums.config import ResolvedConfig, write_resolved
from spacedrums.contracts import (
    AudioEvent,
    CommittedStrike,
    FrameSample,
    HandObservation,
    ImageCrop,
    ImageRef,
    StickObservation,
    StrikeCandidate,
    TimingRecord,
    TrackState,
    TrajectoryPrediction,
)
from spacedrums.timing import CLOCK_ID, wall_clock_iso
from spacedrums.timing.logger import RecordStreamWriter, stream_header

RECORD_TYPES: dict[str, type] = {
    "HandObservation": HandObservation,
    "StickObservation": StickObservation,
    "TrackState": TrackState,
    "TrajectoryPrediction": TrajectoryPrediction,
    "StrikeCandidate": StrikeCandidate,
    "CommittedStrike": CommittedStrike,
    "AudioEvent": AudioEvent,
}


class SessionRecorder:
    def __init__(
        self,
        output_dir: str | Path,
        *,
        session_id: str,
        config: ResolvedConfig,
        git_sha: str,
        producer: str,
        store_crop: str = "FULL",
        extra_meta: dict[str, Any] | None = None,
    ) -> None:
        self.dir = Path(output_dir) / session_id
        if self.dir.exists() and any(self.dir.iterdir()):
            raise FileExistsError(f"session directory {self.dir} already exists and is not empty")
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        (self.dir / "records").mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.config = config
        self.git_sha = git_sha
        self.producer = producer
        self.store_crop = ImageCrop(store_crop)
        self.meta: dict[str, Any] = {
            "session_id": session_id,
            "producer": producer,
            "config_hash": config.config_hash,
            "git_sha": git_sha,
            "clock_id": CLOCK_ID,
            "started_at": wall_clock_iso(),
            "store_crop": str(self.store_crop),
            "frames": 0,
            "note": (
                "Phase 05 developer-session provenance; NOT the Phase 06 SessionMetadata "
                "record (no participant, no consent record, no dataset)"
            ),
            **(extra_meta or {}),
        }
        write_resolved(config, self.dir / "config.snapshot.yaml")
        self._frames = (self.dir / "frames.jsonl").open("w", encoding="utf-8", newline="\n")

        def header(record_type: str, version: str, derived: bool) -> dict[str, Any]:
            return stream_header(
                record_type=record_type,
                record_schema_version=version,
                session_id=session_id,
                config_hash=config.config_hash,
                git_sha=git_sha,
                clock_id=CLOCK_ID,
                producer=producer,
                derived=derived,
            )

        self.streams: dict[str, RecordStreamWriter] = {
            name: RecordStreamWriter(
                self.dir / "records" / f"{name}.jsonl", header(name, cls.SCHEMA_VERSION, True)
            )
            for name, cls in RECORD_TYPES.items()
        }
        self.timing = RecordStreamWriter(
            self.dir / "timing.jsonl", header("TimingRecord", TimingRecord.SCHEMA_VERSION, True)
        )
        self.n = 0

    # -- per frame -------------------------------------------------------------------------
    def write_frame(
        self,
        sample: FrameSample,
        image: np.ndarray | None,
        result: FrameResult,
        observations: dict[Any, tuple[HandObservation, StickObservation]],
    ) -> FrameSample:
        rel = f"frames/frame_{sample.frame_id:06d}.png"
        if image is not None:
            to_store = image
            if self.store_crop is ImageCrop.ROI:
                to_store = crop_roi(image, Roi.from_rect(sample.roi_px))
            if not cv2.imwrite(str(self.dir / rel), to_store, [cv2.IMWRITE_PNG_COMPRESSION, 1]):
                raise OSError(f"cannot write {self.dir / rel}")
        stored = FrameSample(
            **{**sample.__dict__, "image_ref": ImageRef.file(rel, sample.frame_id, self.store_crop)}
        )
        self._frames.write(json.dumps(stored.to_dict(), allow_nan=False) + "\n")
        for h in HANDS:
            hand_obs, stick_obs = observations[h]
            self.streams["HandObservation"].write(hand_obs)
            self.streams["StickObservation"].write(stick_obs)
            hf = result.hands[h]
            self.streams["TrackState"].write(hf.track)
            if hf.prediction is not None:
                self.streams["TrajectoryPrediction"].write(hf.prediction)
            for c in hf.candidates:
                self.streams["StrikeCandidate"].write(c)
            for c in hf.commits:
                self.streams["CommittedStrike"].write(c)
            for e in hf.audio:
                self.streams["AudioEvent"].write(e)
        for rec in result.timing:
            self.timing.write(rec)
        self.n += 1
        return stored

    def flush(self) -> None:
        self._frames.flush()
        for s in self.streams.values():
            s.flush()
        self.timing.flush()

    def close(self, summary: dict[str, Any] | None = None) -> Path:
        self._frames.close()
        for s in self.streams.values():
            s.close()
        self.timing.close()
        self.meta["frames"] = self.n
        self.meta["finished_at"] = wall_clock_iso()
        if summary:
            self.meta["summary"] = summary
        (self.dir / "session.json").write_text(
            json.dumps(self.meta, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        return self.dir


__all__ = ["RECORD_TYPES", "SessionRecorder"]
