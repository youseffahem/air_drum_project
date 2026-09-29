"""Shared fixtures for the live mirror tests: real renders and a spy that locates every text drawn."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from spacedrums.app import main as app_main
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.synthetic import scenario
from spacedrums.capture import Roi
from spacedrums.config import load_config
from spacedrums.contracts import Arm, HandId
from spacedrums.data.recorder import GuidedRecorder
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui import OverlayConfig, OverlayStyle, RuntimeStats, WizardView, draw_guide, draw_wizard

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
CFG = load_config(CONFIG)
REGISTRY = ZoneRegistry.from_config(CFG["zones"])
ROI = Roi.from_rect(CFG["roi"]["px"])
_PUT_TEXT = cv2.putText


def asymmetric_frame() -> np.ndarray:
    frame = np.zeros((480, 640, 3), np.uint8)
    # Physical right hand appears at camera-left before mirror presentation.
    frame[150:190, 100:120] = (0, 0, 255)
    frame[280:310, 500:530] = (255, 0, 0)
    return frame


def stick_analysis(dx: int) -> SimpleNamespace:
    """Duck-typed ``StickAnalysis`` so the full overlay draws regions, candidates and axes."""
    return SimpleNamespace(
        region=SimpleNamespace(
            polygon_px=np.array([[100 + dx, 200], [180 + dx, 190], [190 + dx, 300], [110 + dx, 310]]),
            empty=False,
            span_px=120.0,
        ),
        grip_px=(140 + dx, 250),
        prior_dir_px=(0.3, -0.9),
        segment=SimpleNamespace(candidate_px=np.array([[120 + dx + i, 220 + 2 * i] for i in range(40)])),
        axis=SimpleNamespace(origin_px=(140 + dx, 250), support_far_px=(170 + dx, 180)),
    )


@cache
def busy_frame():
    """(sample, observations, FrameResult) of the synthetic frame with the most candidates/commits."""
    pipeline = DecisionPipeline(
        CFG.data,
        registry=REGISTRY,
        session_id="synthetic-preview",
        active_arm=Arm(CFG["arms"]["active"]),
        shadow_arms=tuple(Arm(a) for a in CFG["arms"]["shadow"]),
        hardware_id="HW-01",
        config_hash=CFG.config_hash,
        audio=AudioOutput(CFG.data, latency=OutputLatency.unmeasured(), device_enabled=False),
    )
    best, score = None, -1
    for sample, observations in scenario("alternating_two_zones", REGISTRY):
        result = pipeline.step(sample, observations, t_now=sample.t_frame_available)
        busy = 10 * len(result.commits) + sum(len(h.candidates) for h in result.hands.values())
        if busy > score:
            best, score = (sample, observations, result), busy
    return best


def cue_hook(roi_canvas, registry: ZoneRegistry) -> None:
    """The real guided-protocol cues: cued-zone highlight, zone name, countdown and metronome."""
    spec = SimpleNamespace(zone_ids=("hihat",), duration_s=2.0, tempo_bpm=90)
    recorder = SimpleNamespace(spec=spec, done=False, t_deadline=11.0, last_t=10.5)
    GuidedRecorder.draw_cues(recorder, roi_canvas, registry)


def app_render(mode: str) -> Callable[[bool], np.ndarray]:
    def make(mirror: bool) -> np.ndarray:
        sample, observations, result = busy_frame()
        return app_main.render(
            asymmetric_frame(),
            ROI,
            REGISTRY,
            result,
            observations,
            Arm.A,
            OverlayStyle(show_candidates=False, show_region=False),
            ["Protocol: hit the Hi-Hat", "second status line"],
            cue_hook,
            OverlayConfig.for_mode(mode),
            RuntimeStats("A", None, 29.7, 3, 0, 0),
            {HandId.LEFT: stick_analysis(0), HandId.RIGHT: stick_analysis(260)},
            mirror=mirror,
        )

    return make


def wizard_render(mirror: bool) -> np.ndarray:
    view = WizardView(
        3, 5, "Zones", "REVIEW", lines=("Hit the highlighted zone",), keys="[space] next  [q] quit",
        progress=0.35, envelope=(0.1, 0.2, 0.8, 0.9), registry=REGISTRY, highlight_zone="hihat",
        status_lines=("status: ok",),
    )
    return draw_wizard(asymmetric_frame(), ROI, view, mirror=mirror)


def guide_render(mirror: bool) -> np.ndarray:
    return draw_guide(asymmetric_frame(), ROI, status_lines=["measured 29.9 fps | dropped 0"], mirror=mirror)


RENDERERS = {
    "app experiment": app_render("experiment"),
    "app full": app_render("full"),
    "wizard": wizard_render,
    "guide": guide_render,
}


@dataclass(frozen=True)
class TextCall:
    text: str
    x: int  # org in the final image (the call may draw on an ROI view of it)
    y: int
    top: int  # origin of the drawn-on view inside the final image
    left: int
    shape: tuple[int, ...]
    font: int
    scale: float
    color: tuple[int, ...]
    thickness: int
    line_type: int


@contextmanager
def spy_text() -> Iterator[list]:
    raw: list = []

    def put_text(img, text, org, font, scale, color, thickness=1, line_type=cv2.LINE_8, *rest, **kw):
        raw.append((img, text, org, font, scale, color, thickness, line_type))
        return _PUT_TEXT(img, text, org, font, scale, color, thickness, line_type, *rest, **kw)

    cv2.putText = put_text
    try:
        yield raw
    finally:
        cv2.putText = _PUT_TEXT


def locate(raw: list, image: np.ndarray) -> list[TextCall]:
    """Resolve each recorded text to final-image coordinates; every text must land in ``image``."""
    calls = []
    base = image.__array_interface__["data"][0]
    for target, text, org, font, scale, color, thickness, line_type in raw:
        assert np.shares_memory(target, image), f"{text!r} was drawn off the displayed image"
        top, rest = divmod(target.__array_interface__["data"][0] - base, image.strides[0])
        left = rest // image.strides[1]
        calls.append(TextCall(
            text, int(org[0]) + left, int(org[1]) + top, top, left, target.shape, font, scale,
            tuple(int(c) for c in color), thickness, line_type,
        ))
    return calls


def render_with_text(make: Callable[[bool], np.ndarray], mirror: bool) -> tuple[np.ndarray, list[TextCall]]:
    with spy_text() as raw:
        image = make(mirror)
    return image, locate(raw, image)


def _near(pixels: np.ndarray, color: tuple[int, ...]) -> np.ndarray:
    return np.all(np.abs(pixels.astype(np.int16) - np.asarray(color, np.int16)) <= 48, axis=-1)


def glyph_scores(image: np.ndarray, call: TextCall) -> tuple[float, float]:
    """Fraction of the text's solid glyph pixels present upright, and present left-right reversed."""
    ref = np.zeros(call.shape, np.uint8)
    org = (call.x - call.left, call.y - call.top)
    _PUT_TEXT(ref, call.text, org, call.font, call.scale, call.color, call.thickness, call.line_type)
    core = _near(ref, call.color)
    cols = np.flatnonzero(core.any(axis=0))
    if cols.size == 0:  # clipped away entirely
        return float("nan"), float("nan")
    reversed_core = core.copy()
    reversed_core[:, cols[0] : cols[-1] + 1] = core[:, cols[0] : cols[-1] + 1][:, ::-1]
    region = image[call.top : call.top + call.shape[0], call.left : call.left + call.shape[1]]
    hit = _near(region, call.color)
    reversed_only = reversed_core & ~core
    return float(hit[core].mean()), float(hit[reversed_only].mean()) if reversed_only.any() else 0.0
