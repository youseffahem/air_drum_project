"""Render the README pictures and GIFs from the project's own UI code.

    python scripts/make_readme_assets.py                  # everything into docs/assets/readme/
    python scripts/make_readme_assets.py --only kit       # kit | setup | fullkit | research

Every picture shows the seven-piece kit of ``app.play --demo --kit full``
(``configs/demo.fullkit.candidate.yaml``): the stick and fingertip demos, the layout-preview flow and the
research overlay drawn on the same seven zones.

**Everything produced here is SYNTHETIC** (integrity I-4): a stylised backdrop, scripted stick and
fingertip paths, scripted key presses and, for the research overlay, the analytic scenarios of
``spacedrums.app.synthetic``. The decisions drawn on the pictures (commits, candidates, predictions) are
computed by the real ``DecisionPipeline``; the frames are drawn by the real ``StageRenderer``,
``LayoutPreview`` and ``draw_scientific_overlay``; the stick ends and fingertips are measured on the
synthetic pixels and landmarks by the real endpoint estimators. Only the MediaPipe hand model is replaced
by synthetic landmarks (as in ``tests/product``). The window chrome, the sound chips and the captions
around each frame are README annotation, drawn here. Nothing is a recording, a measurement or evidence,
and every file name carries ``synthetic``.
"""

from __future__ import annotations

import argparse
import copy
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from spacedrums.app import play
from spacedrums.app.main import Perception, render
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.red_tip_perception import RedTipPerception
from spacedrums.app.synthetic import ROI_PX, build_sequence, scenario
from spacedrums.calib.developer_demo import DeveloperDemoLayout, check_kit_pads
from spacedrums.calib.reach import ReachSettings
from spacedrums.capture import Roi
from spacedrums.config import config_hash, load_config, validate
from spacedrums.contracts import FrameView, HandId, HandObservation, ImageRef
from spacedrums.geometry import ZoneRegistry
from spacedrums.stick.visible import FingertipEndpointEstimator
from spacedrums.ui import OverlayConfig, OverlayStyle, RuntimeStats
from spacedrums.ui.layout_preview import LayoutPreview
from spacedrums.ui.preview_tone import PreviewSettings, PreviewTone
from spacedrums.ui.stage import StageRenderer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
W, H = 640, 480
FPS_SIM = 30.0  # the synthetic timeline (never a camera rate)
PAD_W = 0.17  # go-around width of ``hand_path`` when the next pad lies right below the previous one
STICK_PX = 84  # synthetic stick, grip to tip, camera pixels
RED_CAP_PX, RED_CAP_BGR = 6, (40, 38, 200)  # the painted tip of a synthetic stick
FINGER_PX = 30  # synthetic index finger, knuckle to tip, camera pixels
CAPTION_KIT = "SYNTHETIC input, 30 fps timeline  |  real stage renderer and decision code  |  not a recording"
CAPTION_SETUP = "SYNTHETIC frames and key presses  |  real layout preview and decision code  |  illustration"
CAPTION_RES = "SYNTHETIC stroke, 30 fps analytic timeline  |  real DecisionPipeline  |  not a measurement"
TITLE_RES = "Research overlay  -  seven-piece kit  -  arm A active, arm B shadow"
RIGHT, LEFT = HandId.RIGHT, HandId.LEFT
AUDIO_OFF = SimpleNamespace(device_state="DISABLED")  # no sound device in a README render

PAGE = (11, 15, 30)  # window background, RGB
CHROME = (27, 33, 51)
INK = (232, 236, 247)
MUTED = (143, 152, 181)
# The seven pieces in display order (left to right): chip label, zone id, source drum, and the stage
# renderer's accent colour (``ui.stage.ACCENTS``, converted to RGB).
KIT = (
    ("CRASH", "crash", "18in crash", (255, 190, 60)),
    ("HI-HAT", "hihat", "14in closed", (255, 235, 80)),
    ("SNARE", "snare", "14x5 snare", (255, 90, 90)),
    ("TOM 1", "tom1", "12x7 tom", (60, 150, 255)),
    ("TOM 2", "tom2", "derived tom", (70, 205, 225)),
    ("FLOOR", "floor_tom", "14x14 floor", (255, 110, 210)),
    ("RIDE", "ride", "20in ride", (120, 230, 140)),
)

# Scripted strokes, camera-space hands: RIGHT plays the display-left pieces, LEFT the display-right ones.
# A stroke never travels down through another pad's top edge (that would be a real strike): the move from
# tom 1 to the hi-hat passes under the crash, and the floor tom is reached beside tom 2, not through it.
_UNDER_CRASH = [(0.70, 0.40)]
_BESIDE_TOM2 = [(0.50, 0.33), (0.50, 0.555)]
FINGER_HITS = {
    RIGHT: [(0.50, "hihat"), (1.05, "hihat"), (1.70, "snare"), (2.50, "crash"), (3.20, "tom1"),
            (3.90, "hihat", _UNDER_CRASH), (4.60, "snare"), (5.25, "snare")],
    LEFT: [(0.80, "ride"), (1.40, "ride"), (2.10, "tom2"), (2.85, "floor_tom", _BESIDE_TOM2), (3.55, "ride"),
           (4.20, "tom2"), (4.90, "floor_tom", _BESIDE_TOM2), (5.60, "ride")],
}
STICK_HITS = {
    RIGHT: [(0.50, "snare"), (1.10, "snare"), (1.80, "crash"), (2.60, "tom1"), (3.35, "hihat", _UNDER_CRASH),
            (4.00, "hihat"), (4.70, "snare"), (5.30, "snare")],
    LEFT: [(0.80, "ride"), (1.45, "tom2"), (2.20, "floor_tom", _BESIDE_TOM2), (2.95, "floor_tom"),
           (3.65, "ride"), (4.35, "ride"), (5.05, "tom2"), (5.70, "ride")],
}


# ----------------------------------------------------------------------------- fonts and window chrome


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    try:
        import matplotlib

        face = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        dejavu = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / face
    except ImportError:  # pragma: no cover - matplotlib is a runtime dependency
        dejavu = None
    for name in (*names, *([str(dejavu)] if dejavu else [])):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_center(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fnt, fill) -> None:
    draw.text(xy, text, font=fnt, fill=fill, anchor="mm")


def window(
    content_bgr: np.ndarray,
    title: str,
    caption: str,
    *,
    chips: tuple[tuple[str, str, bool, tuple[int, int, int]], ...] = (),
    strip: Image.Image | None = None,
) -> Image.Image:
    """Dark window around one rendered frame; chips (label, sub-label, lit, RGB), strip and caption are
    README annotation."""
    pad, bar = 22, 38
    h, w = content_bgr.shape[:2]
    chips_h = 52 if chips else 0
    strip_h = strip.height + 14 if strip is not None else 0
    total_w, total_h = w + 2 * pad, pad + bar + h + chips_h + strip_h + 44
    img = Image.new("RGB", (total_w, total_h), PAGE)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((pad - 2, pad - 2, pad + w + 2, pad + bar + h + 2), 14, fill=CHROME)
    for i, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        draw.ellipse((pad + 14 + i * 22, pad + 12, pad + 26 + i * 22, pad + 24), fill=colour)
    text_center(draw, (total_w / 2, pad + bar / 2), title, font(15, True), MUTED)
    frame = Image.fromarray(cv2.cvtColor(content_bgr, cv2.COLOR_BGR2RGB))
    mask = Image.new("L", frame.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, -20, w, h), 12, fill=255)
    img.paste(frame, (pad, pad + bar), mask)
    y = pad + bar + h + 12
    if chips:
        cell = w / len(chips)
        small = len(chips) > 4
        for i, (label, sub, active, colour) in enumerate(chips):
            x0 = pad + i * cell + (3 if small else 6)
            box = (x0, y, x0 + cell - (6 if small else 12), y + 38)
            if active:
                glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
                ImageDraw.Draw(glow).rounded_rectangle(box, 19, fill=(*colour, 90))
                img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"))
                draw = ImageDraw.Draw(img)
            draw.rounded_rectangle(box, 19, fill=colour if active else (24, 30, 48),
                                   outline=colour if active else (52, 60, 88), width=2)
            text_center(draw, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 - 7), label,
                        font(11 if small else 13, True), (12, 14, 26) if active else MUTED)
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 + 9)
            text_center(draw, centre, sub, font(9 if small else 10),
                        (12, 14, 26) if active else (96, 106, 138))
        y += chips_h
    if strip is not None:
        img.paste(strip, (pad, y))
        y += strip.height + 14
    text_center(draw, (total_w / 2, total_h - 20), caption, font(12), MUTED)
    return img


def save_gif(frames: list[Image.Image], path: Path, durations_ms: list[int]) -> None:
    """One shared 255-colour palette from a sample of the frames keeps the files small and stable."""
    step = max(1, len(frames) // 14)
    sample = frames[::step]
    w, h = frames[0].size
    sheet = Image.new("RGB", (w, h * len(sample)))
    for i, frame in enumerate(sample):
        sheet.paste(frame, (0, i * h))
    palette = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    # No error diffusion: it spreads a local change over the rest of the frame and bloats the file.
    out = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    out[0].save(path, save_all=True, append_images=out[1:], duration=durations_ms, loop=0, optimize=False)
    print(f"  {path.relative_to(ROOT)}  {len(frames)} frames  {path.stat().st_size / 1e6:.2f} MB")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1e3:.0f} KB")


# ----------------------------------------------------------------------------- the stylised "camera" frame


def backdrop() -> np.ndarray:
    """A dim room: gradient wall, soft light, floor, bokeh and static grain (static keeps GIFs small)."""
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = (yy / H)[..., None]
    img = np.array([58, 64, 92], np.float32) * (1 - t) + np.array([34, 38, 58], np.float32) * t
    d = np.sqrt(((xx - W * 0.5) / (W * 0.6)) ** 2 + ((yy - H * 0.35) / (H * 0.65)) ** 2)
    img += (np.clip(1 - d, 0, 1) ** 2)[..., None] * np.array([30, 26, 38], np.float32)
    img[yy > H * 0.90] *= 0.80
    bokeh = np.zeros((H, W, 3), np.float32)
    for _ in range(14):
        c = (int(rng.integers(40, W - 40)), int(rng.integers(30, 190)))
        cv2.circle(bokeh, c, int(rng.integers(10, 26)), tuple(float(v) for v in rng.choice(
            [(60, 46, 28), (28, 44, 62), (52, 30, 58)])), -1, cv2.LINE_AA)
    img += cv2.GaussianBlur(bokeh, (0, 0), 6)
    img += rng.normal(0, 1.6, (H, W, 1)).astype(np.float32)
    return img


def capsule(layer: np.ndarray, p0, p1, r0: float, r1: float, colour, s: int) -> None:
    """A tapered limb segment on the supersampled layer."""
    p0, p1 = np.asarray(p0, np.float32) * s, np.asarray(p1, np.float32) * s
    v = p1 - p0
    n = np.array([-v[1], v[0]], np.float32) / max(1e-3, float(np.hypot(*v)))
    poly = np.array([p0 + n * r0 * s, p1 + n * r1 * s, p1 - n * r1 * s, p0 - n * r0 * s], np.int32)
    cv2.fillConvexPoly(layer, poly, colour, cv2.LINE_AA)
    cv2.circle(layer, tuple(int(v) for v in p0), int(r0 * s), colour, -1, cv2.LINE_AA)
    cv2.circle(layer, tuple(int(v) for v in p1), int(r1 * s), colour, -1, cv2.LINE_AA)


def elbow(shoulder, fist, upper: float = 112.0, fore: float = 112.0) -> tuple[float, float]:
    sx, sy = shoulder
    dx, dy = fist[0] - sx, fist[1] - sy
    dist = min(max(1e-3, float(np.hypot(dx, dy))), (upper + fore) * 0.995)
    base = math.atan2(dy, dx)
    off = math.acos(max(-1.0, min(1.0, (upper * upper + dist * dist - fore * fore) / (2 * upper * dist))))
    cands = [
        (sx + upper * math.cos(base + sgn * off), sy + upper * math.sin(base + sgn * off)) for sgn in (1, -1)
    ]
    return max(cands, key=lambda c: c[1])  # elbows hang down and out


def figure(base: np.ndarray, fists: dict[HandId, tuple[float, float]]) -> np.ndarray:
    """Upper-body silhouette with rim light, drawn 2x supersampled; returns RGB uint8."""
    s = 2
    layer = np.zeros((H * s, W * s, 3), np.uint8)
    mask = np.zeros((H * s, W * s), np.uint8)
    cx = W // 2
    body = (104, 114, 144)
    skin = (214, 160, 134)
    shoulders = {LEFT: (cx - 66, 156), RIGHT: (cx + 66, 156)}
    cv2.fillPoly(layer, [np.array([[cx - 70, 150], [cx + 70, 150], [cx + 52, 360], [cx - 52, 360]]) * s],
                 body, cv2.LINE_AA)
    cv2.circle(layer, (cx * s, 156 * s), 6, body, -1)
    cv2.ellipse(layer, (cx * s, 152 * s), (86 * s, 26 * s), 0, 180, 360, body, -1, cv2.LINE_AA)
    cv2.rectangle(layer, ((cx - 13) * s, 112 * s), ((cx + 13) * s, 152 * s), body, -1)
    cv2.ellipse(layer, (cx * s, 84 * s), (30 * s, 36 * s), 0, 0, 360, body, -1, cv2.LINE_AA)
    for hand, fist in fists.items():
        sh = shoulders[hand]
        el = elbow(sh, fist)
        capsule(layer, sh, el, 15, 11.5, body, s)
        capsule(layer, el, fist, 11.5, 9, body, s)
    mask[:] = (layer.sum(axis=2) > 0) * 255
    for fist in fists.values():
        cv2.circle(layer, (int(fist[0] * s), int(fist[1] * s)), 12 * s, skin, -1, cv2.LINE_AA)
    mask = np.maximum(mask, (layer.sum(axis=2) > 0) * 255).astype(np.uint8)
    rim = cv2.subtract(mask, cv2.erode(mask, np.ones((7, 7), np.uint8)))
    rim = cv2.GaussianBlur(rim, (0, 0), 1.6)
    yy = np.linspace(1.0, 0.55, H * s, dtype=np.float32)[:, None, None]
    layer = np.clip(layer.astype(np.float32) * (0.78 + 0.28 * yy), 0, 255)
    layer += (rim.astype(np.float32) / 255)[..., None] * np.array([46, 52, 70], np.float32)
    layer = cv2.resize(layer, (W, H), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(np.minimum(mask, 255).astype(np.float32) / 255, (W, H), interpolation=cv2.INTER_AREA)
    out = base * (1 - alpha[..., None]) + layer * alpha[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------- scripted stick paths


def smooth(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def hand_path(hits: list[tuple], zones: dict[str, tuple[float, float]]):
    """Tip position (ROI-normalised) over time for one hand: lift, travel (around a pad when the next
    pad lies below it in the same column), accelerating stroke through the top edge, rebound.
    A hit may carry a third item, ROI points the tip travels through on its way to that pad (to pass
    beside a pad instead of striking down through its top edge)."""
    down, rise, height, depth = 0.21, 0.20, 0.105, 0.03
    f = height / (height + depth)
    way: list[tuple[float, float, float, str]] = []  # (t, x, y, kind)
    via: dict[float, list[tuple[float, float]]] = {}  # approach time -> travel points
    for t_hit, zone, *through in sorted(hits):
        x, y = zones[zone]
        t_a = t_hit - math.sqrt(f) * down
        if through:
            via[t_a] = through[0]
        way += [(t_a, x, y - height, "A"), (t_a + down, x, y + depth, "S"),
                (t_a + down + rise, x, y - height * 0.9, "B")]
    first = way[0]

    def at(t: float, period: float) -> tuple[float, float]:
        t = t % period
        pts = [(0.0, first[1], first[2], "A"), *way]
        end = (period, first[1], first[2], "A")
        pts.append(end)
        for (t0, x0, y0, k0), (t1, x1, y1, k1) in zip(pts, pts[1:], strict=False):
            if t0 <= t <= t1:
                u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                if k0 == "A" and k1 == "S":
                    return x0, y0 + (y1 - y0) * u * u  # accelerating
                if k0 == "S" and k1 == "B":
                    return x0, y0 + (y1 - y0) * (1 - (1 - u) ** 2)  # decelerating rebound
                if k0 == "B" and k1 == "A" and t1 in via:
                    return _bend([(x0, y0), *via[t1], (x1, y1)], smooth(u))
                if k0 == "B" and k1 == "A" and abs(x1 - x0) < 1e-6 and y1 > y0 + 0.02:
                    side = 1 if x0 > 0.5 else -1  # next pad lies below: go around the pad, outwards
                    wx = x0 + side * (PAD_W * 0.5 + 0.09)
                    return _bend([(x0, y0), (wx, y0 + 0.03), (wx, y1 - 0.01), (x1, y1)], smooth(u))
                lift = 0.045 * math.sin(math.pi * u) if abs(x1 - x0) > 1e-6 else 0.0
                return x0 + (x1 - x0) * smooth(u), y0 + (y1 - y0) * smooth(u) - lift
        return first[1], first[2]

    return at


def _bend(points: list[tuple[float, float]], u: float) -> tuple[float, float]:
    seg = [math.dist(a, b) for a, b in zip(points, points[1:], strict=False)]
    target = u * sum(seg)
    for (a, b), length in zip(zip(points, points[1:], strict=False), seg, strict=False):
        if target <= length or (a, b) == (points[-2], points[-1]):
            v = 0.0 if length == 0 else min(1.0, target / length)
            return a[0] + (b[0] - a[0]) * v, a[1] + (b[1] - a[1]) * v
        target -= length
    return points[-1]


# ----------------------------------------------------------------------------- synthetic hands


def finger_hand(frame_id: int, t: float, hand: HandId, tip: np.ndarray) -> HandObservation:
    """A hand pointing down: index fingertip (landmark 8) at ``tip``, its knuckle (5) above it. The
    fingertip estimator reads only these two landmarks; the others sit in the fist above the knuckle."""
    knuckle = tip - [0, FINGER_PX]
    lm = np.tile(knuckle - [0, 14], (21, 1)).astype(float)
    lm[0] = knuckle - [0, 34]
    lm[5], lm[6], lm[7], lm[8] = knuckle, knuckle + [0, FINGER_PX / 3], knuckle + [0, 2 * FINGER_PX / 3], tip
    return HandObservation(frame_id, t, hand, True, "SYNTHETIC", tuple(map(tuple, lm / [W, H])), None, 0.95,
                           (0, 0, 1, 1))


# ----------------------------------------------------------------------------- the seven-piece kit, live path


class FullKit:
    """``app.play --demo --kit full`` on synthetic frames: the configured seven-piece kit, the shared
    decision pipeline and the stage renderer with the default (natural) preview. ``mode`` picks the tip
    source: ``fingers`` (``--fingers``, the fingertip estimator on synthetic hand landmarks) or ``red``
    (``--red-tips``, the red-tip detector and tracker on the synthetic pixels; no hand model)."""

    def __init__(self, *, mode: str) -> None:
        self.mode = mode
        self.cfg = play.play_config(demo=True, kit="full", red_tips=mode == "red")
        self.roi = Roi.from_rect([0, 0, W, H])
        self.clock = [100.0]
        self.hands: dict[HandId, HandObservation] = {}
        rig = self

        class SyntheticHands:
            def __init__(self, settings):
                self.asset = SimpleNamespace(sha256="SYNTHETIC")

            def detect(self, view):
                return SimpleNamespace(left=rig.hands[LEFT], right=rig.hands[RIGHT], processing_s=0.0)

            def close(self):
                pass

        if mode == "red":  # as app.play --red-tips
            self.perception = RedTipPerception(self.cfg)
        else:  # as app.play --fingers
            with mock.patch("spacedrums.hands.HandLandmarker", SyntheticHands):
                self.perception = Perception(self.cfg)
            self.perception.estimator = FingertipEndpointEstimator(self.perception.stick_settings)
        settings = PreviewSettings.from_config(self.cfg["product"].get("preview")).preset("natural")
        self.stage = StageRenderer(dim=settings.dim, vignette=settings.vignette)
        self.tone = PreviewTone(settings)
        self.base = backdrop()
        self.set_pads(self.cfg["product"]["developer_demo"]["pads"])

    def set_pads(self, pads: list[dict]) -> None:
        """As app.play after a layout-preview nudge: new zones, registry and decision state."""
        self.cfg["product"]["developer_demo"]["pads"] = [dict(p) for p in pads]
        self.cfg["zones"] = DeveloperDemoLayout(self.cfg).zones
        validate(self.cfg)
        self.registry = ZoneRegistry.from_config(self.cfg["zones"])
        self.pipeline = DecisionPipeline(
            self.cfg, registry=self.registry, session_id="README-SYNTHETIC", active_arm="A",
            hardware_id="SYNTHETIC", config_hash=config_hash(self.cfg), audio=None,
            clock=lambda: self.clock[0], gain_fn=lambda z, p: 0.5, developer_demo=True,
        )

    def anchors(self) -> dict[str, tuple[float, float]]:
        """(x centre, y of the top strike edge) of every pad, camera ROI units."""
        return {z.zone_id: (sum(p[0] for p in z.shape.points) / len(z.shape.points), z.impact_surface.p0[1])
                for z in self.registry}

    def step(self, sample, tips: dict[HandId, np.ndarray]):
        """Draw the synthetic camera frame for these tips (camera pixels), then run perception and the
        decision pipeline on it. Returns (view, endpoint evidence, pipeline result)."""
        fingers = self.mode == "fingers"
        reach = FINGER_PX if fingers else STICK_PX
        fists = {h: (float(t[0]), float(t[1] - reach)) for h, t in tips.items()}
        img = cv2.cvtColor(figure(self.base, fists), cv2.COLOR_RGB2BGR)
        colour, width = ((134, 160, 214), 7) if fingers else ((200, 222, 236), 6)
        for h, tip in tips.items():
            grip = tuple(int(v) for v in fists[h])
            cv2.line(img, grip, tuple(int(v) for v in tip), colour, width, cv2.LINE_AA)
            if not fingers:  # the painted cap
                cv2.circle(img, tuple(int(v) for v in tip), RED_CAP_PX, RED_CAP_BGR, -1, cv2.LINE_AA)
        if fingers:
            self.hands = {h: finger_hand(sample.frame_id, sample.t_capture, h, tips[h]) for h in tips}
        sample = replace(sample, roi_px=(0, 0, W, H), image_ref=ImageRef.memory(img))
        view = FrameView(sample, img, img)
        self.clock[0] = sample.t_frame_available
        observations = self.perception(view)
        evidence = self.perception.estimator.evidence
        result = self.pipeline.step(sample, observations, t_now=self.clock[0], endpoint_evidence=evidence)
        return view, evidence, result

    def render(self, view, evidence, result) -> np.ndarray:
        shown = self.tone(view.full)
        return self.stage.render(shown, self.roi, self.registry, evidence, result, audio=AUDIO_OFF)

    def close(self) -> None:
        self.perception.close()


def samples(seconds: float):
    """Synthetic capture samples of the 30 fps timeline (the frame ids and clock of ``app.synthetic``)."""
    registry = ZoneRegistry.from_config(DeveloperDemoLayout(play.play_config(demo=True, kit="full")).zones)
    return [s for s, _ in build_sequence(registry, [], duration_s=seconds)]


def groove(rig: FullKit, hits: dict, period: float) -> tuple[list[np.ndarray], list[list[str]]]:
    """Play the scripted strokes once; returns the stage frames and the committed zones per frame."""
    paths = {h: hand_path(v, rig.anchors()) for h, v in hits.items()}
    frames, commits = [], []
    for sample in samples(period):
        t = sample.frame_id / FPS_SIM
        tips = {h: np.array(p(t, period)) * [W, H] for h, p in paths.items()}
        view, evidence, result = rig.step(sample, tips)
        frames.append(rig.render(view, evidence, result))
        commits.append([c.zone_id for c in result.commits])
    return frames, commits


def check(name: str, hits: dict, commits: list[list[str]]) -> None:
    order = [(round(n / FPS_SIM, 2), z) for n, cs in enumerate(commits) for z in cs]
    expected = sorted(hit[1] for v in hits.values() for hit in v)
    print(f"  {name}: {len(order)} commits for {len(expected)} scripted strokes")
    print("   commits:", order)
    if sorted(z for _, z in order) != expected:
        print("   WARNING: commits differ from the scripted strokes; check the pictures")


def chips_at(commits: list[list[str]], n: int) -> tuple:
    """The seven sound chips; a chip glows for 0.3 s after each commit on its piece."""
    glow = int(0.30 * FPS_SIM)
    lit = {z for k in range(max(0, n - glow), n + 1) for z in commits[k]}
    return tuple((label, sub, zid in lit, rgb) for label, zid, sub, rgb in KIT)


def kit_gif(frames, commits, title: str, path: Path) -> None:
    gif, durations = [], []
    for n in range(0, len(frames), 3):  # 10 frames/s of the 30 fps timeline keeps the file small
        small = cv2.resize(frames[n], (600, 450), interpolation=cv2.INTER_AREA)
        gif.append(window(small, title, CAPTION_KIT, chips=chips_at(commits, n)))
        durations.append(100)
    save_gif(gif, path, durations)


def make_kit() -> None:
    """The seven-piece kit played with red-tipped sticks (``app.play --demo --kit full --red-tips``, a
    coloured-marker mode). The visible-endpoint estimator for plain sticks loses the tip where a synthetic
    stick crosses the synthetic body, so it is not used for this picture."""
    rig = FullKit(mode="red")
    frames, commits = groove(rig, STICK_HITS, 6.0)
    rig.close()
    check("kit (sticks)", STICK_HITS, commits)
    title = "Space Drums  -  seven-piece kit, red-tipped sticks"
    kit_gif(frames, commits, title, OUT / "kit-demo-synthetic.gif")
    still = max(range(len(frames)), key=lambda n: sum(len(c) for c in commits[max(0, n - 8): n + 1]))
    small = cv2.resize(frames[still], (640, 480), interpolation=cv2.INTER_AREA)
    still_img = window(small, title, CAPTION_KIT, chips=chips_at(commits, still))
    save_png(still_img, OUT / "kit-product-view-synthetic.png")


def make_fullkit() -> None:
    """The seven-piece kit played with fingertips (``app.play --demo --kit full --fingers``)."""
    rig = FullKit(mode="fingers")
    frames, commits = groove(rig, FINGER_HITS, 6.0)
    rig.close()
    check("fullkit (fingers)", FINGER_HITS, commits)
    kit_gif(frames, commits, "Space Drums  -  seven-piece kit, fingertips as sticks",
            OUT / "full-kit-stage-synthetic.gif")


# ----------------------------------------------------------------------------- setup flow (layout preview)


def make_setup() -> None:
    """The seven-piece kit's setup flow, ``app.play --demo --fingers --layout-preview``: a short groove
    builds the measured reach, then scripted key presses move, scale and save the kit. The preview,
    its messages and the validation of every nudge are the app's own."""
    rig = FullKit(mode="fingers")
    reach = ReachSettings(**rig.cfg["product"].get("reach", {}))
    preview = LayoutPreview(rig.cfg["product"]["developer_demo"]["pads"],
                            lambda pads: check_kit_pads(pads, (rig.roi.w, rig.roi.h), reach),
                            save_dir=Path("data") / "dev-product" / "dev-product-SYNTHETIC")
    hits = {RIGHT: [(0.45, "hihat"), (1.05, "snare"), (1.75, "crash"), (2.50, "tom1")],
            LEFT: [(0.75, "ride"), (1.40, "tom2"), (2.15, "floor_tom", _BESIDE_TOM2)]}
    play_s, freeze_s = 3.0, 2.78  # hands hold still after the last rebound
    keys = [("2  MOVE", "k", "down")] * 3 + [("2  MOVE", "l", "right")] * 2 + \
           [("3  SCALE", "]", "larger")] * 2 + [("3  SCALE", "[", "smaller"), ("4  SAVE", "s", "save")]
    paths = {h: hand_path(v, rig.anchors()) for h, v in hits.items()}
    seq = samples(play_s + len(keys) / FPS_SIM + 0.2)
    gif, durations = [], []

    def frame(sample, tips, title, ms):
        """Every frame is processed and rendered, as in the app; ``ms=None`` leaves it out of the GIF."""
        view, evidence, result = rig.step(sample, tips)
        preview.observe(evidence, result)
        img = rig.render(view, evidence, result)
        preview.draw(img, rig.stage, rig.roi, W)
        if ms is not None:
            small = cv2.resize(img, (720, 540), interpolation=cv2.INTER_AREA)
            gif.append(window(small, f"Space Drums  -  seven-piece kit setup  -  {title}", CAPTION_SETUP))
            durations.append(ms)

    n_play = int(play_s * FPS_SIM)
    held = {}
    for sample in seq[:n_play]:
        t = min(sample.frame_id / FPS_SIM, freeze_s)
        held = {h: np.array(p(t, 99.0)) * [W, H] for h, p in paths.items()}
        frame(sample, held, "1  PLAY  (your reach builds up)", 100 if sample.frame_id % 3 == 0 else None)
    durations[-1] = 900
    for (stage, key, what), sample in zip(keys, seq[n_play:], strict=False):
        if key == "s":
            with tempfile.TemporaryDirectory() as tmp:  # the message names the relative session path
                cwd = os.getcwd()
                os.chdir(tmp)
                try:
                    (Path(tmp) / preview.save_dir).mkdir(parents=True)
                    preview.handle_key(ord(key))
                finally:
                    os.chdir(cwd)
        else:
            moved = preview.handle_key(ord(key))
            if moved is not None:
                rig.set_pads(moved)  # zones, registry and decision state, as app.play does
        frame(sample, held, f"{stage}  (key {key}: {what})", 600)
    durations[-1] = 2200
    rig.close()
    print(f"  setup: final message: {preview.message}")
    save_gif(gif, OUT / "layout-preview-flow-synthetic.gif", durations)


# ----------------------------------------------------------------------------- research overlay


class Ticker:
    """Deterministic stand-in for ``timing.now``."""

    def __init__(self, start: float = 500.0, step: float = 0.001) -> None:
        self.t, self.step = start, step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def research_background() -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = (yy / H)[..., None]
    img = np.array([34, 24, 14], np.float32) * (1 - t) + np.array([20, 14, 10], np.float32) * t
    grid = ((xx % 40 < 1) | (yy % 40 < 1))[..., None] * np.array([7, 6, 5], np.float32)
    return np.clip(img + grid, 0, 255).astype(np.uint8)


def make_research() -> None:
    """The research application's arms (prototype configuration) on the seven-piece kit's zones: arm A
    active, arm B in shadow, the analytic ``alternating_two_zones`` scenario on the snare and floor tom."""
    cfg = copy.deepcopy(load_config(ROOT / "configs" / "prototype.candidate.yaml").data)
    cfg["zones"] = DeveloperDemoLayout(play.play_config(demo=True, kit="full")).zones
    validate(cfg)
    registry = ZoneRegistry.from_config(cfg["zones"])
    clock = Ticker()
    pipeline = DecisionPipeline(
        cfg, registry=registry, session_id="README-SYNTHETIC", active_arm="A", shadow_arms=("B",),
        hardware_id="SYNTHETIC", config_hash=config_hash(cfg), audio=None, clock=clock,
        gain_fn=lambda z, p: 0.5,
    )
    seq = scenario("alternating_two_zones", registry, zone="snare", zone2="floor_tom")
    roi, style, base = Roi.from_rect(ROI_PX), OverlayStyle(), research_background()
    results = []
    for sample, obs in seq:
        results.append((obs, pipeline.step(sample, obs, t_now=sample.t_frame_available)))
    first_rule = reactive = None
    for k, (_, res) in enumerate(results):
        for hf in res.hands.values():
            for c in hf.candidates:
                if str(c.source) == "RULE" and first_rule is None:
                    first_rule = k
                if str(c.source) == "REACTIVE" and reactive is None:
                    reactive = k
    print(f"  research: first RULE candidate at frame {first_rule}, REACTIVE crossing at frame {reactive}")
    lo, hi = max(0, first_rule - 6), min(len(results) - 1, reactive + 19)
    commit_frames = {k for k, (_, r) in enumerate(results) if r.commits}
    gif, durations = [], []
    for k in range(lo, hi + 1):
        obs, res = results[k]
        shown = render(base, roi, registry, res, obs, pipeline.active_arm, style,
                       overlay_config=OverlayConfig(), runtime=RuntimeStats(active_arm="A"))
        strip = timeline(k, lo, hi, first_rule, reactive)
        gif.append(window(shown, TITLE_RES, CAPTION_RES, strip=strip))
        durations.append(900 if k in commit_frames else 170)
    save_gif(gif, OUT / "research-overlay-synthetic.gif", durations)
    obs, res = results[reactive]
    shown = render(base, roi, registry, res, obs, pipeline.active_arm, style, overlay_config=OverlayConfig(),
                   runtime=RuntimeStats(active_arm="A"))
    save_png(window(shown, TITLE_RES, CAPTION_RES, strip=timeline(reactive, lo, hi, first_rule, reactive)),
             OUT / "research-overlay-synthetic.png")


def timeline(k: int, lo: int, hi: int, first_rule: int | None, reactive: int | None) -> Image.Image:
    """Frame ruler under the overlay: where arm B's candidate first appears and where arm A crosses."""
    w, h = W, 74
    img = Image.new("RGB", (w, h), (20, 26, 44))
    d = ImageDraw.Draw(img)
    x0, x1, y = 24, w - 24, 34
    step = (x1 - x0) / (hi - lo)
    for f in range(lo, hi + 1):
        x = x0 + (f - lo) * step
        d.line((x, y - 4, x, y + 4), fill=(70, 80, 112), width=1)
    d.line((x0, y, x1, y), fill=(70, 80, 112), width=1)

    def mark(frame: int | None, colour, label: str, above: bool) -> None:
        if frame is None or not lo <= frame <= hi:
            return
        x = x0 + (frame - lo) * step
        d.polygon([(x, y - 9), (x + 6, y), (x, y + 9), (x - 6, y)], fill=colour)
        text_center(d, (x, y - 22 if above else y + 22), label, font(11, True), colour)

    mark(first_rule, (250, 210, 80), f"B  RULE candidate  f{first_rule}", True)
    mark(reactive, (70, 200, 245), f"A  REACTIVE crossing + commit  f{reactive}", False)
    px = x0 + (k - lo) * step
    d.line((px, y - 14, px, y + 14), fill=(255, 255, 255), width=2)
    d.text((8, 6), f"frame {k}", font=font(11), fill=MUTED)
    return img


# ----------------------------------------------------------------------------- main


STEPS = {"kit": make_kit, "setup": make_setup, "fullkit": make_fullkit, "research": make_research}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=tuple(STEPS), default=None)
    args = ap.parse_args(argv)
    cv2.setNumThreads(1)
    for name, fn in STEPS.items():
        if args.only in (None, name):
            print(f"[{name}]")
            fn()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
