"""Live mirror on real pixels: the mirrored window has no path back into processing.

``test_live_preview.py`` proves this with a stubbed perception. Here the real hand landmarker and
stick estimator run on a developer capture through the app's live code path (``--source live``), once
with the mirrored window and once headless. Every record stream must be identical, the camera frames
must be unchanged, and the recorded frames must keep the camera pixels. Live decisions read the wall
clock; both runs use the frame clock (``t_now = t_frame_available``, as replay does) so the two are
comparable. Needs the git-ignored capture and MediaPipe model.
"""

from importlib import import_module
from pathlib import Path

import cv2
import numpy as np
import pytest

from spacedrums.app import main as app_main
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.capture.replay import ReplayFrameSource
from spacedrums.contracts.schema import repo_root
from spacedrums.timing.logger import read_record_stream

ROOT = repo_root()
CAPTURE = ROOT / "data" / "dev-captures" / "swing-L2-exp-5"
MODEL = ROOT / "assets" / "models" / "hand_landmarker.task"

pytestmark = pytest.mark.skipif(
    not (CAPTURE / "frames.jsonl").exists() or not MODEL.exists(),
    reason="developer capture or MediaPipe model file absent (git-ignored)",
)


@pytest.fixture
def frame_clock(monkeypatch):
    step = DecisionPipeline.step

    def at_frame_time(self, sample, observations, *, t_now=None, **kwargs):
        t_now = sample.t_frame_available if t_now is None else t_now
        return step(self, sample, observations, t_now=t_now, **kwargs)

    monkeypatch.setattr(DecisionPipeline, "step", at_frame_time)


def run_live(monkeypatch, out: Path, window: bool):
    source = ReplayFrameSource(CAPTURE)
    views, renders, displayed = [], [], []

    def frames(*_):
        def gen():
            for sample in source:
                view = source.view(sample)
                views.append((view, view.full.copy()))
                yield sample, view, None

        return gen(), (lambda: None), {"source": "live"}, None

    render = app_main.render

    def spy_render(*args, **kwargs):
        renders.append(kwargs.get("mirror"))
        return render(*args, **kwargs)

    monkeypatch.setattr(app_main, "render", spy_render)
    monkeypatch.setattr(cv2, "imshow", lambda window_name, image: displayed.append(image.shape))
    monkeypatch.setattr(cv2, "namedWindow", lambda *args: None)
    monkeypatch.setattr(cv2, "destroyAllWindows", lambda: None)
    monkeypatch.setattr(cv2, "pollKey", lambda: -1)
    monkeypatch.setattr(cv2, "waitKey", lambda delay: -1)
    args = app_main.build_parser().parse_args(
        [
            "--source",
            "live",
            "--no-audio",
            "--record",
            "--output-dir",
            str(out),
            "--log-dir",
            str(out / "logs"),
            "--session-id",
            "mirror-real-frames",
            *([] if window else ["--no-window"]),
        ]
    )
    summary = app_main.run(args, source_factory=frames)
    return Path(summary["session_dir"]), views, renders, displayed


def test_mirrored_live_window_leaves_real_perception_and_decisions_unchanged(
    monkeypatch, tmp_path, frame_clock
):
    shown, views, renders, displayed = run_live(monkeypatch, tmp_path / "window", window=True)
    headless, _, no_renders, _ = run_live(monkeypatch, tmp_path / "headless", window=False)
    n = len(views)
    assert n == 171 and renders == [True] * n and len(displayed) == n and no_renders == []
    for view, pixels in views:
        np.testing.assert_array_equal(view.full, pixels)  # the window never writes to capture memory
    source = ReplayFrameSource(CAPTURE)
    for sample in source:
        saved = cv2.imread(str(shown / "frames" / f"frame_{sample.frame_id:06d}.png"))
        np.testing.assert_array_equal(saved, source.read_image(sample))  # recordings keep camera pixels

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    comparison = import_module("regenerate_session").compare_streams(shown, headless)
    assert comparison["decision_identical"] and comparison["max_abs_diff"] == 0.0, comparison["streams"]
    assert (shown / "frames.jsonl").read_bytes() == (headless / "frames.jsonl").read_bytes()
    hands = read_record_stream(shown / "records" / "HandObservation.jsonl")[1]
    sticks = read_record_stream(shown / "records" / "StickObservation.jsonl")[1]
    candidates = read_record_stream(shown / "records" / "StrikeCandidate.jsonl")[1]
    # the comparison covers real detections, both hand slots, sticks and zone decisions
    assert {r["hand_id"] for r in hands if r["present"]} == {"LEFT", "RIGHT"}
    assert sum(r["present"] for r in sticks) > 100 and candidates
