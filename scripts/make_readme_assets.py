"""Render the README pictures and GIFs from the project's own UI code.

    python scripts/make_readme_assets.py                  # everything into docs/assets/readme/
    python scripts/make_readme_assets.py --only kit       # kit | calibration | research

**Everything produced here is SYNTHETIC** (integrity I-4): a stylised backdrop, scripted stick paths and,
for the research overlay, the analytic scenarios of ``spacedrums.app.synthetic``. The decisions drawn on
the pictures (commits, candidates, predictions) are computed by the real ``DecisionPipeline`` and the
frames are drawn by the real ``render_kit`` / ``draw_scientific_overlay``; the stick endpoints of the kit
animation are measured on the synthetic pixels by the real ``VisibleEndpointEstimator``. Only the
MediaPipe hand model is replaced by synthetic landmarks (as in ``tests/product``). The window chrome,
the sound chips and the captions around each frame are README annotation, drawn here. Nothing is a
recording, a measurement or evidence, and every file name carries ``synthetic``.
"""

from __future__ import annotations

import argparse
import math
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
from spacedrums.app.synthetic import ROI_PX, build_sequence, scenario
from spacedrums.capture import Roi
from spacedrums.config import config_hash, load_config, validate
from spacedrums.contracts import FrameView, HandId, HandObservation, ImageRef
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.four_pad import SAMPLES, four_pad_layout
from spacedrums.ui import OverlayConfig, OverlayStyle, RuntimeStats
from spacedrums.ui.kit import render_kit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
W, H = 640, 480
FPS_SIM = 30.0  # the synthetic timeline (never a camera rate)

# An illustrative layout for the pictures (pads enlarged and centred on the figure). The fixed
# developer guide and the calibrated layouts come from the calibration code, not from here.
COLUMNS, ROWS, PAD_W, PAD_H = (0.25, 0.75), (0.50, 0.73), 0.17, 0.115
STICK_PX = 120
CAPTION_KIT = "SYNTHETIC input  |  real renderer and decision code  |  illustration, not a recording"
CAPTION_CAL = "SYNTHETIC frames  |  the messages are the app's own  |  illustration"
CAPTION_RES = "SYNTHETIC stroke, 30 fps analytic timeline  |  real DecisionPipeline  |  not a measurement"
TITLE_RES = "Research overlay  -  arm A active, arm B shadow"
RIGHT, LEFT = HandId.RIGHT, HandId.LEFT

PAGE = (11, 15, 30)  # window background, RGB
CHROME = (27, 33, 51)
INK = (232, 236, 247)
MUTED = (143, 152, 181)
ZONE_RGB = {
    "crash_ride": (250, 210, 80),
    "hihat": (70, 200, 245),
    "snare": (255, 110, 215),
    "tom1": (110, 224, 90),
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
    chips: tuple[tuple[str, str, bool], ...] = (),
    strip: Image.Image | None = None,
) -> Image.Image:
    """Dark window around one rendered frame; chips/strip/caption are README annotation."""
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
        for i, (label, sub, active) in enumerate(chips):
            x0 = pad + i * cell + 6
            box = (x0, y, x0 + cell - 12, y + 38)
            colour = ZONE_RGB.get(sub, (70, 200, 245))
            if active:
                glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
                ImageDraw.Draw(glow).rounded_rectangle(box, 19, fill=(*colour, 90))
                img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"))
                draw = ImageDraw.Draw(img)
            draw.rounded_rectangle(box, 19, fill=colour if active else (24, 30, 48),
                                   outline=colour if active else (52, 60, 88), width=2)
            text_center(draw, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 - 7), label, font(13, True),
                        (12, 14, 26) if active else MUTED)
            text_center(draw, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 + 9), SAMPLES.get(sub, sub),
                        font(10), (12, 14, 26) if active else (96, 106, 138))
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


def elbow(shoulder, fist, hand: HandId, upper: float = 112.0, fore: float = 112.0) -> tuple[float, float]:
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
        el = elbow(sh, fist, hand)
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


def hand_path(hits: list[tuple[float, str]], zones: dict[str, tuple[float, float]]):
    """Tip position (ROI-normalised) over time for one hand: lift, travel (around a pad when the next
    pad lies below it in the same column), accelerating stroke through the top edge, rebound."""
    down, rise, height, depth = 0.21, 0.20, 0.105, 0.03
    f = height / (height + depth)
    way: list[tuple[float, float, float, str]] = []  # (t, x, y, kind)
    for t_hit, zone in sorted(hits):
        x, y = zones[zone]
        t_a = t_hit - math.sqrt(f) * down
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


# ----------------------------------------------------------------------------- the product decision path


def zone_anchors() -> dict[str, tuple[float, float]]:
    """(x centre, y of the top strike edge) of every pad, camera coordinates."""
    cfg = play.play_config(demo=True)
    cfg["zones"] = four_pad_layout(COLUMNS, ROWS, PAD_W, PAD_H)
    return {z.zone_id: (sum(p[0] for p in z.shape.points) / len(z.shape.points), z.impact_surface.p0[1])
            for z in ZoneRegistry.from_config(cfg["zones"])}


def synthetic_hand(frame_id: int, t: float, hand: HandId, grip: np.ndarray) -> HandObservation:
    """A closed fist, rotated 180 degrees, with its stick pointing down (as in tests/product)."""
    lm = np.zeros((21, 2))
    lm[0] = grip - [12, 27]
    for f, k in enumerate((5, 9, 13, 17)):
        b = grip - [0, f * 10]
        lm[k] = b
        lm[k + 1], lm[k + 2], lm[k + 3] = b - [8, 0], b - [15, 0], b - [21, 0]
    lm[1], lm[2], lm[3], lm[4] = grip - [6, 10], grip - [10, 4], grip - [12, -3], grip - [13, -9]
    return HandObservation(frame_id, t, hand, True, "SYNTHETIC", tuple(map(tuple, lm / [W, H])), None, 0.95,
                           (0, 0, 1, 1))


def draw_scene(sample, tips: dict[HandId, np.ndarray], base: np.ndarray) -> tuple[np.ndarray, dict]:
    fists = {h: (float(t[0]), float(t[1] - STICK_PX)) for h, t in tips.items()}
    rgb = figure(base, fists)
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    for h, tip in tips.items():
        grip = np.array(fists[h])
        cv2.line(img, tuple(grip.astype(int)), tuple(tip.astype(int)), (200, 222, 236), 6, cv2.LINE_AA)
    hands = {h: synthetic_hand(sample.frame_id, sample.t_capture, h, np.array(fists[h])) for h in tips}
    return img, hands


def kit_run(hits: dict[HandId, list[tuple[float, str]]], period: float):
    """Run the product decision path over the scripted strokes; yields (display, commits) per frame."""
    cfg = play.play_config(demo=True)
    cfg["zones"] = four_pad_layout(COLUMNS, ROWS, PAD_W, PAD_H)
    validate(cfg)
    registry = ZoneRegistry.from_config(cfg["zones"])
    anchors = zone_anchors()
    paths = {h: hand_path(v, anchors) for h, v in hits.items()}
    base = backdrop()
    seq = build_sequence(registry, [], duration_s=period)
    rows = []
    for sample, _ in seq:
        t = sample.frame_id / FPS_SIM
        tips = {h: np.array(p(t, period)) * [W, H] for h, p in paths.items()}
        img, hands = draw_scene(sample, tips, base)
        sample = replace(sample, roi_px=(0, 0, W, H), image_ref=ImageRef.memory(img))
        rows.append((FrameView(sample, img, img), hands))
    lookup = {v.sample.frame_id: h for v, h in rows}

    class SyntheticHands:
        def __init__(self, settings):
            self.asset = SimpleNamespace(sha256="SYNTHETIC")

        def detect(self, view):
            h = lookup[view.sample.frame_id]
            return SimpleNamespace(left=h[LEFT], right=h[RIGHT], processing_s=0.0)

        def close(self):
            pass

    body = SimpleNamespace(left=0.40, right=0.60, shoulder_y=0.31, hip_y=0.72)
    roi = Roi.from_rect([0, 0, W, H])
    clock = [100.0]
    with mock.patch("spacedrums.hands.HandLandmarker", SyntheticHands):
        perception = Perception(cfg)
    pipeline = DecisionPipeline(
        cfg, registry=registry, session_id="README-SYNTHETIC", active_arm="A", hardware_id="SYNTHETIC",
        config_hash=config_hash(cfg), audio=None, clock=lambda: clock[0], gain_fn=lambda z, p: 0.5,
        developer_demo=True,
    )
    for view, _ in rows:
        clock[0] = view.sample.t_frame_available
        observations = perception(view)
        result = pipeline.step(view.sample, observations, t_now=clock[0],
                               endpoint_evidence=perception.estimator.evidence)
        shown = render_kit(view.full, roi, registry, sticks=[s for _, s in observations.values()], body=body,
                           message="DEV fixed guide: cross a yellow top edge downward; lift out to repeat")
        yield shown, [c.zone_id for c in result.commits]
    perception.close()


def make_kit() -> None:
    hits = {
        RIGHT: [(0.60, "crash_ride"), (1.50, "snare"), (2.10, "snare"), (2.70, "snare"), (3.60, "crash_ride"),
                (4.50, "snare")],
        LEFT: [(0.60, "hihat"), (1.20, "hihat"), (1.80, "hihat"), (2.70, "tom1"), (3.30, "tom1"),
               (4.20, "hihat")],
    }
    expected = sorted((round(t, 2), z) for v in hits.values() for t, z in v)
    period = 5.4
    frames, committed, order = [], [], []
    for n, (shown, commits) in enumerate(kit_run(hits, period)):
        frames.append(shown)
        committed.append(commits)
        order += [(round(n / FPS_SIM, 2), z) for z in commits]
    print(f"  kit: {len(order)} commits for {len(expected)} scripted strokes")
    print("   commits:", order)
    if sorted(z for _, z in order) != sorted(z for _, z in expected):
        print("   WARNING: commits differ from the scripted strokes; check the pictures")
    chips = ("CRASH / RIDE", "crash_ride"), ("HI-HAT", "hihat"), ("SNARE", "snare"), ("TOM 1", "tom1")
    glow = int(0.30 * FPS_SIM)
    caption = CAPTION_KIT
    gif, durations = [], []
    for n in range(0, len(frames), 2):
        active = {z for k in range(max(0, n - glow), n + 1) for z in committed[k]}
        gif.append(window(frames[n], "Space Drums  -  fixed-guide demo path",
                          caption, chips=tuple((lab, zid, zid in active) for lab, zid in chips)))
        durations.append(67)
    save_gif(gif, OUT / "kit-demo-synthetic.gif", durations)
    still = max(range(len(frames)), key=lambda n: sum(len(c) for c in committed[max(0, n - 8): n + 1]))
    active = {z for k in range(max(0, still - glow), still + 1) for z in committed[k]}
    save_png(window(frames[still], "Space Drums  -  fixed-guide demo path", caption,
                    chips=tuple((lab, zid, zid in active) for lab, zid in chips)),
             OUT / "kit-product-view-synthetic.png")


# ----------------------------------------------------------------------------- calibration flow


def make_calibration() -> None:
    """The four states of the product's automatic calibration, with the app's own messages."""
    cfg = play.play_config(demo=True)
    cfg["zones"] = four_pad_layout(COLUMNS, ROWS, PAD_W, PAD_H)
    registry = ZoneRegistry.from_config(cfg["zones"])
    anchors = zone_anchors()
    body = SimpleNamespace(left=0.40, right=0.60, shoulder_y=0.31, hip_y=0.72)
    roi = Roi.from_rect([0, 0, W, H])
    base = backdrop()
    states = [
        ("1  STAND", None, None, "Stand in the frame, with your waist and both sticks in view", False),
        ("2  REACH", registry, "crash_ride", "Play relaxed strokes at Crash / Ride; alternate your hands",
         True),
        ("3  VERIFY", registry, "crash_ride", "Try the fitted Crash / Ride with both hands", True),
        ("4  READY", registry, None, "Ready to play", False),
    ]
    right = hand_path([(0.45, "crash_ride"), (1.05, "crash_ride")], anchors)
    rest = {LEFT: np.array([0.27, 0.58]) * [W, H], RIGHT: np.array([0.73, 0.58]) * [W, H]}
    frames, durations = [], []
    sample = build_sequence(registry, [], duration_s=0.2).frames[0][0]
    for label, reg, target, message, moving in states:
        n_frames = 14 if moving else 6
        for k in range(n_frames):
            tips = dict(rest)
            if moving:
                tips[RIGHT] = np.array(right(k * 0.1, 1.5)) * [W, H]
            else:
                tips[RIGHT] = rest[RIGHT]
            img, _ = draw_scene(sample, tips, base)
            sticks = [SimpleNamespace(present=True, axis_origin=((t[0]) / W, (t[1] - STICK_PX) / H),
                                      tip=(t[0] / W, t[1] / H)) for t in tips.values()]
            shown = render_kit(img, roi, reg, sticks=sticks, body=body, message=message, target=target)
            title = f"Space Drums  -  automatic calibration  -  {label}"
            frames.append(window(shown, title, CAPTION_CAL))
            durations.append(110 if moving else 330)
        durations[-1] = 900
    save_gif(frames, OUT / "calibration-flow-synthetic.gif", durations)


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
    cfg = load_config(ROOT / "configs" / "prototype.candidate.yaml")
    registry = ZoneRegistry.from_config(cfg["zones"])
    clock = Ticker()
    pipeline = DecisionPipeline(
        cfg.data, registry=registry, session_id="README-SYNTHETIC", active_arm="A", shadow_arms=("B",),
        hardware_id="SYNTHETIC", config_hash=cfg.config_hash, audio=None, clock=clock,
        gain_fn=lambda z, p: 0.5,
    )
    seq = scenario("alternating_two_zones", registry)
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
    lo, hi = 9, 36
    commit_frames = {k for k, (_, r) in enumerate(results) if r.commits}
    gif, durations = [], []
    for k in range(lo, hi + 1):
        obs, res = results[k]
        shown = render(base, roi, registry, res, obs, pipeline.active_arm, style,
                       overlay_config=OverlayConfig(), runtime=RuntimeStats(active_arm="A"))
        strip = timeline(k, lo, hi, first_rule, reactive, commit_frames)
        gif.append(window(shown, TITLE_RES, CAPTION_RES, strip=strip))
        durations.append(900 if k in commit_frames else 170)
    save_gif(gif, OUT / "research-overlay-synthetic.gif", durations)
    obs, res = results[reactive]
    shown = render(base, roi, registry, res, obs, pipeline.active_arm, style, overlay_config=OverlayConfig(),
                   runtime=RuntimeStats(active_arm="A"))
    save_png(window(shown, TITLE_RES, CAPTION_RES,
                    strip=timeline(reactive, lo, hi, first_rule, reactive, commit_frames)),
             OUT / "research-overlay-synthetic.png")


def timeline(
    k: int, lo: int, hi: int, first_rule: int | None, reactive: int | None, commits: set[int]
) -> Image.Image:
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("kit", "calibration", "research"), default=None)
    args = ap.parse_args(argv)
    cv2.setNumThreads(1)
    steps = {"kit": make_kit, "calibration": make_calibration, "research": make_research}
    for name, fn in steps.items():
        if args.only in (None, name):
            print(f"[{name}]")
            fn()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
