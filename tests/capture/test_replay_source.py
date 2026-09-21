"""TEST-CONFORM-7 (replay case): ``ReplayFrameSource`` reproduces recorded timestamps with REPLAY label."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from spacedrums.capture import ReplayFrameSource
from spacedrums.contracts import FrameSample, FrameSource, ImageRef, TimestampSource
from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[2]
DEV_CAPTURE = ROOT / "data" / "dev-captures" / "swing-L2-exp-5"


def _write_session(tmp: Path, n: int = 4, crop: str = "FULL") -> Path:
    (tmp / "frames").mkdir(parents=True)
    with (tmp / "frames.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for i in range(n):
            img = np.full((48, 64, 3), 10 * i, np.uint8)
            rel = f"frames/frame_{i:06d}.png"
            assert cv2.imwrite(str(tmp / rel), img)
            s = FrameSample(
                frame_id=i,
                t_capture=50.0 + i / 30,
                t_frame_available=50.002 + i / 30,
                timestamp_source=TimestampSource.GRAB_RETURN,
                frame_size_px=(64, 48),
                roi_px=(4, 4, 56, 40),
                image_ref=ImageRef.file(rel, i, crop),
                camera_profile_id="synthetic",
                dropped_since_last=i % 2,
            )
            fh.write(json.dumps(s.to_dict()) + "\n")
    return tmp


def test_replay_reproduces_timestamps_and_labels_replay(tmp_path):
    d = _write_session(tmp_path / "s")
    src = ReplayFrameSource(d)
    assert isinstance(src, FrameSource) and len(src) == 4 and src.roi is not None and src.roi.w == 56
    samples = list(src)
    assert [s.frame_id for s in samples] == [0, 1, 2, 3]
    assert all(s.timestamp_source is TimestampSource.REPLAY for s in samples)
    assert [s.t_capture for s in samples] == pytest.approx([50.0 + i / 30 for i in range(4)])
    assert [s.dropped_since_last for s in samples] == [0, 1, 0, 1]
    assert all(contract_schema.is_valid("frame-sample", s.to_dict()) for s in samples)
    view = src.view(samples[2])
    assert view.full is not None and view.full.shape == (48, 64, 3) and view.roi.shape == (40, 56, 3)
    assert int(view.full[0, 0, 0]) == 20
    assert ReplayFrameSource.memory_sample(samples[2], view.full).image_ref.array is view.full
    assert len(ReplayFrameSource(d, limit=2)) == 2


def test_replay_roi_only_recording(tmp_path):
    d = _write_session(tmp_path / "r", crop="ROI")
    src = ReplayFrameSource(d)
    view = src.view(src.samples[0])
    assert view.full is None and view.roi.shape == (48, 64, 3)  # the stored image IS the crop


def test_replay_rejects_bad_streams(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReplayFrameSource(tmp_path / "missing")
    d = _write_session(tmp_path / "bad")
    lines = (d / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    (d / "frames.jsonl").write_text("\n".join([lines[1], lines[0]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="strictly increasing"):
        ReplayFrameSource(d)


@pytest.mark.skipif(not (DEV_CAPTURE / "frames.jsonl").exists(), reason="dev capture not on this machine")
def test_replay_reads_a_phase02_dev_capture():
    src = ReplayFrameSource(DEV_CAPTURE, limit=3)
    s = src.samples[0]
    assert s.timestamp_source is TimestampSource.REPLAY and src.view(s).roi.shape[:2] == (440, 560)
