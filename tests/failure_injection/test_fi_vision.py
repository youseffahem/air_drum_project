"""TEST-FI-VIS-1..3: image-level faults on a developer capture through real perception (Task 17.3).

Occlusion masks around a hand, the hand's side of the ROI blanked (hand out of the ROI), lighting
gain/gamma steps and a background distractor: the live loop keeps every safety invariant and adds
no commit away from the unperturbed replay's commits. The developer capture is git-ignored; the
tests skip with a reason when it (or the MediaPipe model file) is absent. DEVELOPMENT evidence.
"""

from __future__ import annotations

import pytest
from inv_helpers import ROOT, make_pipeline

from spacedrums.app import faults as F
from spacedrums.app.invariants import InvariantMonitor

CAPTURE = ROOT / "data" / "dev-captures" / "swing-L2-exp-5"
MODEL = ROOT / "assets" / "models" / "hand_landmarker.task"
pytestmark = pytest.mark.skipif(
    not (CAPTURE / "frames.jsonl").exists() or not MODEL.exists(),
    reason="developer capture swing-L2-exp-5 or the MediaPipe model file is not present (git-ignored)",
)
FRAMES = 90  # the first three seconds keep the suite fast


def _replay(cfg, registry, plan=None):
    from spacedrums.app.main import Perception
    from spacedrums.capture import ReplayFrameSource

    src = ReplayFrameSource(CAPTURE, limit=FRAMES)
    pipe = make_pipeline(cfg, registry, active="A", shadow=("B",))
    monitor = InvariantMonitor.for_pipeline(pipe, mode="raise")
    perception = Perception(cfg.data)
    results = []
    try:
        for i, sample in enumerate(src):
            view = src.view(sample)
            if plan is not None:
                view = plan.apply_image(view, i)
            r = pipe.step(sample, perception(view), t_now=sample.t_frame_available)
            monitor.observe(r, pipe)
            results.append(r)
    finally:
        perception.close()
    return results, monitor.finish()


@pytest.fixture(scope="module")
def reference(cfg, registry):
    return _replay(cfg, registry)


def _commit_frames(results):
    return {(r.sample.frame_id, str(c.hand_id)) for r in results for c in r.commits if not c.shadow}


def _near(added, reference_frames, slack=2):
    return all(any(abs(f - g) <= slack and h == k for g, k in reference_frames) for f, h in added)


@pytest.mark.parametrize(
    "name,fn",
    [
        ("occlusion-left-half", lambda v, i: F.mask_region(v, (0.0, 0.0, 0.5, 1.0))),
        ("occlusion-right-half", lambda v, i: F.mask_region(v, (0.5, 0.0, 1.0, 1.0))),
        ("dim", lambda v, i: F.adjust_lighting(v, 0.35, 1.0)),
        ("very-dim", lambda v, i: F.adjust_lighting(v, 0.2, 1.6)),
        ("bright", lambda v, i: F.adjust_lighting(v, 1.8, 0.7)),
    ],
)
def test_image_faults_keep_invariants_and_add_no_commit(cfg, registry, reference, name, fn):
    plan = F.FaultPlan().image(30, 60, name.upper(), fn)
    results, summary = _replay(cfg, registry, plan)
    assert summary["violations_total"] == 0
    ref_frames = _commit_frames(reference[0])
    added = _commit_frames(results) - ref_frames
    assert _near(added, ref_frames), (name, sorted(added))


def test_background_distractor_adds_no_commit(cfg, registry, reference):
    def distractor(view, i):
        out = F.mask_region(view, (0.0, 0.0, 0.0, 0.0))
        h, w = out.roi.shape[:2]
        x = int((0.1 + 0.8 * ((i % 60) / 60.0)) * w)
        out.roi[int(0.05 * h) : int(0.25 * h), max(0, x - 3) : x + 3] = (40, 30, 20)
        return out

    results, summary = _replay(cfg, registry, F.FaultPlan().image(0, FRAMES, "DISTRACTOR", distractor))
    assert summary["violations_total"] == 0
    ref_frames = _commit_frames(reference[0])
    assert _near(_commit_frames(results) - ref_frames, ref_frames)
