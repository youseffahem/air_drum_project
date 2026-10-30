# ruff: noqa: E501  (SVG markup literals)
"""Rebuild the HUD of the owner's AR-view concept render as animated vector UI (README showcase).

    python scripts/make_ar_ui_concept.py                  # docs/assets/readme/ar-ui-concept.svg
    python scripts/make_ar_ui_concept.py --debug          # also draw the pad ellipses for alignment checks

Input: ``docs/assets/readme/source/ar-concept-photo.jpg``, the concept render supplied by the project
owner. The baked-in HUD of that picture (panels, drum labels, leader lines) is removed with OpenCV
inpainting to get a clean plate; the interface is then redrawn as vector UI at the same positions and
animated with SMIL and CSS only (no scripts, no external files, so GitHub renders it inside an ``<img>``).

**This is a concept, not a screenshot.** The photo is a design render, the HUD values (FPS, latency,
sensitivity, volume) are placeholders, and the hits are a scripted loop. The picture says so in its own
corner ("CONCEPT RENDER · NOT A SCREENSHOT") and the README caption repeats it. Nothing here is a
measurement (integrity I-1, I-4, I-5).
"""

from __future__ import annotations

import argparse
import base64
import io
import math
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_readme_svgs as ms  # noqa: E402  (shared SVG helpers: f, rect, text, svg)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "assets" / "readme" / "source" / "ar-concept-photo.jpg"
OUT = ROOT / "docs" / "assets" / "readme" / "ar-ui-concept.svg"

W, H = 1672, 941
CYCLE = 12.0
BEAT = 0.6
f = ms.f

BLUE, RED, GREEN, GOLD = "#2aa8ff", "#ff4b5c", "#2ee87a", "#f5b942"
WHITE, MUTED = "#f4f7ff", "#aab4cc"
# attribute strings kept out of f-string expressions (Python 3.11 forbids backslashes there)
FO55, FO7, FO9 = 'fill-opacity=".55"', 'fill-opacity=".7"', 'fill-opacity=".9"'
FW500, FW600, FW700 = 'font-weight="500"', 'font-weight="600"', 'font-weight="700"'
LS11, LS16 = 'letter-spacing="1.1"', 'letter-spacing="1.6"'


def tl(width: float) -> str:
    """Fixed text width, so the layout does not depend on the viewer's fonts."""
    return f'textLength="{f(width)}" lengthAdjust="spacingAndGlyphs"'


PADS = {
    "crash": dict(name="Crash / Ride", col="#f5b942", c=(282, 480), rx=250, ry=88, rot=9, chip=(176, 317, 171, 45), anchor=(262, 362), dot=(276, 415)),
    "tom": dict(name="Tom", col="#3aa0ff", c=(592, 624), rx=188, ry=55, rot=-1, chip=(406, 707, 89, 46), anchor=(480, 707), dot=(523, 660)),
    "snare": dict(name="Snare", col="#ff4d5e", c=(1006, 648), rx=190, ry=56, rot=2, chip=(1076, 752, 105, 46), anchor=(1086, 752), dot=(1042, 700)),
    "hihat": dict(name="Hi-Hat", col="#34e06b", c=(1382, 585), rx=220, ry=55, rot=3, chip=(1437, 471, 120, 47), anchor=(1466, 518), dot=(1452, 572)),
}
# baked-in HUD rectangles of the source picture (x0, y0, x1, y1), a little generous
PANELS = [(14, 8, 306, 90), (20, 96, 277, 272), (1281, 11, 1663, 297), (0, 845, W, H)]
ORBS = {"L": (633, 237, BLUE), "R": (1118, 199, RED)}


# ----------------------------------------------------------------------------- the picture


def clean_plate(photo: np.ndarray) -> np.ndarray:
    """Remove the baked-in HUD (panels, labels, leader lines) by inpainting; the vector UI replaces it."""
    mask = np.zeros(photo.shape[:2], np.uint8)
    for x0, y0, x1, y1 in PANELS:
        cv2.rectangle(mask, (x0, y0), (x1, y1), 255, -1)
    for p in PADS.values():
        x, y, w, h = p["chip"]
        cv2.rectangle(mask, (x - 4, y - 4), (x + w + 4, y + h + 4), 255, -1)
        cv2.line(mask, p["anchor"], p["dot"], 255, 8, cv2.LINE_AA)
        cv2.circle(mask, p["dot"], 12, 255, -1)
    return cv2.inpaint(photo, mask, 5, cv2.INPAINT_TELEA)


def jpeg_uri(img_bgr: np.ndarray, quality: int) -> str:
    buf = io.BytesIO()
    Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def images(photo_path: Path) -> tuple[str, str]:
    photo = cv2.imread(str(photo_path))
    if photo is None or photo.shape[:2] != (H, W):
        raise SystemExit(f"{photo_path} must be a {W}x{H} picture")
    plate = clean_plate(photo)
    small = cv2.resize(plate, (W // 8, H // 8), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 2.2)
    return jpeg_uri(plate, 80), jpeg_uri(small, 70)


# ----------------------------------------------------------------------------- the scripted groove


def groove() -> dict[str, list[tuple[float, str]]]:
    """A 12 s loop at 100 BPM: right hand hi-hat and snare, left hand crash and tom (hand, not measurement)."""
    out: dict[str, list[tuple[float, str]]] = {k: [] for k in PADS}
    for b in range(20):
        t = round(b * BEAT, 3)
        if b % 4 == 2:
            out["snare"].append((t, "R"))
        else:
            out["hihat"].append((t, "R"))
        if b in (0, 12):
            out["crash"].append((t, "L"))
        if b % 4 == 3:
            out["tom"].append((t, "L"))
    return out


def by_hand(hits: dict[str, list[tuple[float, str]]], hand: str) -> list[float]:
    return sorted(t for v in hits.values() for t, h in v if h == hand)


def track(times: list[float], dur: float, a, b, idle, eps: float = 0.003):
    """keyTimes and values of a one-shot effect repeated at every time in ``times``: idle -> a -> b -> idle."""
    pts: list[tuple[float, object]] = [(0.0, idle)]
    last = 0.0
    for t in sorted(times):
        for tt, v in ((t - eps, idle), (t, a), (min(t + dur, CYCLE - 3 * eps), b), (min(t + dur + eps, CYCLE - 2 * eps), idle)):
            tt = max(tt, last + 1e-4)
            pts.append((tt, v))
            last = tt
    pts.append((CYCLE, idle))
    kt = ";".join(f(min(p[0] / CYCLE, 1.0)) for p in pts)
    vals = ";".join(p[1] if isinstance(p[1], str) else f(p[1]) for p in pts)
    return kt, vals


def anim(attr: str, times, dur, a, b, idle, kind: str = "animate", extra: str = "") -> str:
    kt, vals = track(times, dur, a, b, idle)
    if kind == "animate":
        return f'<animate attributeName="{attr}" dur="{CYCLE}s" repeatCount="indefinite" keyTimes="{kt}" values="{vals}"{extra}/>'
    return f'<animateTransform attributeName="transform" type="{kind}" dur="{CYCLE}s" repeatCount="indefinite" keyTimes="{kt}" values="{vals}"{extra}/>'


# ----------------------------------------------------------------------------- scene effects (aligned with the picture)


def pad_effects(hits: dict[str, list[tuple[float, str]]]) -> str:
    rnd = random.Random(11)
    out = []
    for key, p in PADS.items():
        times = [t for t, _ in hits[key]]
        cx, cy = p["c"]
        col = p["col"]
        long = key == "crash"
        d_ring, d_flash, d_spark = (0.95, 0.55, 0.7) if long else (0.55, 0.34, 0.45)
        out.append(f'<g transform="translate({cx} {cy}) rotate({p["rot"]})">')
        out.append(f'<ellipse rx="{p["rx"]}" ry="{p["ry"]}" fill="{col}" opacity="0">{anim("opacity", times, d_flash, 0.42, 0, 0)}</ellipse>')
        for delay, w_glow, w_core in ((0.0, 10, 3.2), (0.09, 6, 2.0)):
            ts = [t + delay for t in times]
            scale = anim("", ts, d_ring, "0.62 0.62", "1.28 1.28", "0.62 0.62", "scale")
            fade = anim("opacity", ts, d_ring, 0.95, 0, 0)
            out.append(f'<g opacity="0">{fade}'
                       f'<ellipse rx="{p["rx"]}" ry="{p["ry"]}" fill="none" stroke="{col}" stroke-width="{w_glow}" stroke-opacity=".28" vector-effect="non-scaling-stroke">{scale}</ellipse>'
                       f'<ellipse rx="{p["rx"]}" ry="{p["ry"]}" fill="none" stroke="#fff" stroke-width="{w_core}" stroke-opacity=".9" vector-effect="non-scaling-stroke">{scale}</ellipse></g>')
        n = 11 if long else 8
        for i in range(n):
            ang = (i / n) * math.tau + rnd.uniform(-0.25, 0.25)
            dist = rnd.uniform(70, 150) * (1.25 if long else 1.0)
            ln = rnd.uniform(12, 24)
            dx, dy = dist * math.cos(ang), dist * math.sin(ang) * 0.8
            kt, vals = track(times, d_spark, "0 0", f"{f(dx)} {f(dy)}", "0 0")
            ex, ey = ln * math.cos(ang), ln * math.sin(ang)
            out.append(f'<g opacity="0"><animateTransform attributeName="transform" type="translate" dur="{CYCLE}s" repeatCount="indefinite" keyTimes="{kt}" values="{vals}"/>'
                       f'{anim("opacity", times, d_spark, 1, 0, 0)}'
                       f'<line x1="0" y1="0" x2="{f(ex)}" y2="{f(ey)}" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/>'
                       f'<line x1="{f(ex * 0.45)}" y1="{f(ey * 0.45)}" x2="{f(ex)}" y2="{f(ey)}" stroke="{col}" stroke-width="4.4" stroke-linecap="round" stroke-opacity=".75"/></g>')
        out.append("</g>")
    return "".join(out)


def orb_pulses(hits: dict[str, list[tuple[float, str]]]) -> str:
    out = []
    for hand, (x, y, col) in ORBS.items():
        times = by_hand(hits, hand)
        out.append(f'<circle cx="{x}" cy="{y}" r="14" fill="none" stroke="{col}" stroke-width="3" opacity="0">'
                   '<animate attributeName="r" values="12;34" dur="1.6s" repeatCount="indefinite"/>'
                   '<animate attributeName="opacity" values=".85;0" dur="1.6s" repeatCount="indefinite"/></circle>')
        if times:
            out.append(f'<circle cx="{x}" cy="{y}" r="12" fill="{col}" opacity="0">{anim("r", times, 0.4, 12, 46, 12)}{anim("opacity", times, 0.4, 0.55, 0, 0)}</circle>')
    return "".join(out)


def trail_paths() -> str:
    """Swish trails behind the stick tips: dashes run along the arcs."""
    trails = [("M633 237 C 596 226 548 252 520 318", BLUE, 2.8), ("M633 237 C 604 236 566 268 548 322", "#7cc8ff", 1.6),
              ("M1118 199 C 1152 214 1182 262 1192 334", RED, 2.8), ("M1118 199 C 1146 222 1170 270 1176 322", "#ff9aa6", 1.6)]
    out = []
    for i, (d, col, w) in enumerate(trails):
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-dasharray="26 120" opacity=".75">'
                   f'<animate attributeName="stroke-dashoffset" values="0;-146" dur="{1.1 + i * 0.13:.2f}s" repeatCount="indefinite"/></path>')
    return "".join(out)


def orbs_and_trails(hits: dict[str, list[tuple[float, str]]]) -> str:
    return orb_pulses(hits) + trail_paths()


def ar_brackets() -> str:
    """Hand-detection brackets with their LEFT / RIGHT tags."""
    out = []
    for (x0, y0, x1, y1), col, label, lw in (((500, 388, 622, 506), BLUE, "LEFT", 66), ((1008, 376, 1106, 490), RED, "RIGHT", 78)):
        s = 22
        out.append(f'<g fill="none" stroke="{col}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity=".9">'
                   f'<path d="M{x0} {y0 + s}V{y0}H{x0 + s}M{x1 - s} {y0}H{x1}V{y0 + s}M{x1} {y1 - s}V{y1}H{x1 - s}M{x0 + s} {y1}H{x0}V{y1 - s}"/>'
                   '<animate attributeName="opacity" values=".95;.45;.95" dur="1.8s" repeatCount="indefinite"/></g>')
        out.append(f'<g>{ms.rect(x0, y0 - 28, lw, 22, 11, "#06101f", col, 1.4, FO7)}'
                   f'{ms.text(x0 + lw / 2, y0 - 12.5, label, 11, col, "middle", "b", LS16)}</g>')
    return "".join(out)


def ar_scan() -> str:
    return ('<rect x="0" y="-80" width="1672" height="80" fill="url(#scan)">'
            '<animate attributeName="y" values="90;780;780" keyTimes="0;.55;1" dur="9s" repeatCount="indefinite"/></rect>')


def ar_dust() -> str:
    rnd = random.Random(7)
    dust = []
    for _ in range(34):
        x, y = rnd.uniform(20, W - 20), rnd.uniform(120, 840)
        r = rnd.choice([1.2, 1.6, 2.0, 2.6])
        col = rnd.choice(["#ffffff", "#9fd8ff", "#ffd9a0", "#ffb3bd"])
        d, k = rnd.uniform(7, 15), rnd.uniform(0, 12)
        dust.append(f'<circle class="dust" cx="{f(x)}" cy="{f(y)}" r="{r}" fill="{col}" style="animation-duration:{f(d)}s;animation-delay:-{f(k)}s"/>')
    return "".join(dust)


def ar_layer() -> str:
    """Hand-detection brackets, a scan sweep and drifting dust: the 'AR' feel."""
    return ar_brackets() + ar_scan() + ar_dust()


def labels(hits: dict[str, list[tuple[float, str]]], interactive: bool = False) -> str:
    """Drum labels with leader lines; each label glows on its own hits."""
    out = []
    for key, p in PADS.items():
        x, y, w, h = p["chip"]
        col = p["col"]
        times = [t for t, _ in hits[key]]
        ax, ay = p["anchor"]
        dx, dy = p["dot"]
        out.append(f'<line x1="{ax}" y1="{ay}" x2="{dx}" y2="{dy}" stroke="{col}" stroke-width="2.2" stroke-opacity=".9"/>')
        out.append(f'<circle cx="{dx}" cy="{dy}" r="5.5" fill="#fff"/>')
        out.append(f'<circle cx="{dx}" cy="{dy}" r="5.5" fill="none" stroke="{col}" stroke-width="2">'
                   '<animate attributeName="r" values="5.5;17" dur="2.4s" repeatCount="indefinite"/>'
                   '<animate attributeName="opacity" values=".9;0" dur="2.4s" repeatCount="indefinite"/></circle>')
        out.append(f'<circle r="3.4" fill="{col}"><animateMotion dur="2.4s" repeatCount="indefinite" path="M{ax} {ay}L{dx} {dy}"/></circle>')
        out.append(f'<g>{ms.rect(x, y, w, h, 9, "#070d1a", col, 2.4, FO9)}'
                   f'{ms.text(x + w / 2, y + 31, p["name"], 24, WHITE, "middle", "", FW600)}</g>')
        cls = f' class="chipglow" data-pad="{key}"' if interactive else ""
        out.append(f'<rect{cls} x="{x - 3}" y="{y - 3}" width="{w + 6}" height="{h + 6}" rx="12" fill="none" stroke="{col}" stroke-width="5" opacity="0">{anim("opacity", times, 0.5, 0.95, 0, 0)}</rect>')
        if interactive:
            out.append(f'<rect class="hit" data-pad="{key}" x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#fff" fill-opacity="0" pointer-events="all"/>')
    return "".join(out)


# ----------------------------------------------------------------------------- HUD


def glass(pid: str, x, y, w, h, r=14, tint=0.58) -> str:
    """Frosted panel: the blurred picture clipped to the shape, a dark tint and a thin light edge."""
    return (f'<clipPath id="{pid}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/></clipPath>'
            f'<g clip-path="url(#{pid})"><use href="#blur"/><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#060c1c" fill-opacity="{tint}"/></g>'
            f'<rect x="{x + .7}" y="{y + .7}" width="{w - 1.4}" height="{h - 1.4}" rx="{r}" fill="none" stroke="#fff" stroke-opacity=".17" stroke-width="1.4"/>')


def gear(cx: float, cy: float, ro: float = 14.5, ri: float = 10.8, teeth: int = 8) -> str:
    pts = []
    n = teeth * 4
    for i in range(n):
        ang = i / n * math.tau
        rad = ro if i % 4 in (1, 2) else ri
        pts.append(f"{'M' if i == 0 else 'L'}{f(cx + rad * math.cos(ang))} {f(cy + rad * math.sin(ang))}")
    hole = f"M{f(cx + 5.2)} {f(cy)}A5.2 5.2 0 1 0 {f(cx - 5.2)} {f(cy)}A5.2 5.2 0 1 0 {f(cx + 5.2)} {f(cy)}Z"
    return f'<path d="{"".join(pts)}Z {hole}" fill="#fff" fill-rule="evenodd"/>'


def slider(x0: float, x1: float, y: float, frac: float, value_x: float, value: str, sid: str = "") -> str:
    kx = x0 + (x1 - x0) * frac

    def ident(name: str) -> str:
        return f' id="{sid}{name}"' if sid else ""

    hit = (f'<rect id="{sid}Hit" class="hit" x="{x0 - 16}" y="{y - 18}" width="{x1 - x0 + 32}" height="36" fill="#fff" fill-opacity="0" pointer-events="all"/>' if sid else "")
    value_extra = f'id="{sid}Val" {tl(24)}' if sid else tl(24)
    return (f'<rect x="{x0}" y="{y - 4.5}" width="{x1 - x0}" height="9" rx="4.5" fill="#fff" fill-opacity=".26"/>'
            f'<rect{ident("Fill")} x="{x0}" y="{y - 4.5}" width="{f(kx - x0)}" height="9" rx="4.5" fill="url(#slider)"/>'
            f'<circle{ident("Glow")} cx="{f(kx)}" cy="{y}" r="17" fill="{BLUE}" opacity="0"><animate attributeName="opacity" values="0;.38;0" dur="2.4s" repeatCount="indefinite"/><animate attributeName="r" values="12;21;12" dur="2.4s" repeatCount="indefinite"/></circle>'
            f'<circle{ident("Knob")} cx="{f(kx)}" cy="{y}" r="11.5" fill="#eaf5ff" stroke="{BLUE}" stroke-width="3.2"/>'
            f'{ms.text(value_x, y + 7, value, 20, WHITE, "start", "", value_extra)}{hit}')


def dot(cx, cy, col, times: list[float] | None = None) -> str:
    base = f'<circle cx="{cx}" cy="{cy}" r="7.5" fill="{col}"/>'
    if times:
        halo = f'<circle cx="{cx}" cy="{cy}" r="7.5" fill="{col}" opacity="0">{anim("opacity", times, 0.4, 0.7, 0, 0)}{anim("r", times, 0.4, 7.5, 17, 7.5)}</circle>'
    else:
        halo = (f'<circle cx="{cx}" cy="{cy}" r="7.5" fill="none" stroke="{col}" stroke-width="2" opacity="0"><animate attributeName="r" values="7.5;16" dur="2s" repeatCount="indefinite"/>'
                '<animate attributeName="opacity" values=".8;0" dur="2s" repeatCount="indefinite"/></circle>')
    return halo + base


def wood_stick(base: tuple[float, float], tip: tuple[float, float], w0: float, w1: float, glow: str, gid: str) -> str:
    dx, dy = tip[0] - base[0], tip[1] - base[1]
    ln = math.hypot(dx, dy)
    nx, ny = -dy / ln, dx / ln
    p = [(base[0] + nx * w0 / 2, base[1] + ny * w0 / 2), (tip[0] + nx * w1 / 2, tip[1] + ny * w1 / 2),
         (tip[0] - nx * w1 / 2, tip[1] - ny * w1 / 2), (base[0] - nx * w0 / 2, base[1] - ny * w0 / 2)]
    pts = " ".join(f"{f(a)},{f(b)}" for a, b in p)
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{f(base[0])}" y1="{f(base[1])}" x2="{f(tip[0])}" y2="{f(tip[1])}">'
            '<stop offset="0" stop-color="#b9805a"/><stop offset=".55" stop-color="#e2b58f"/><stop offset="1" stop-color="#f1d2b6"/></linearGradient>'
            f'<polygon points="{pts}" fill="none" stroke="{glow}" stroke-width="6" stroke-linejoin="round" opacity=".55" filter="url(#neon)"/>'
            f'<polygon points="{pts}" fill="url(#{gid})" stroke="{glow}" stroke-width="1.6" stroke-linejoin="round"/>')


def tracking_panel(hits: dict[str, list[tuple[float, str]]], interactive: bool = False) -> str:
    out = [glass("gTrack", 1286, 16, 372, 276, 16)]
    out.append(f'<g fill="none" stroke="{WHITE}" stroke-width="2.6" stroke-linecap="round"><path d="M1336.5 40.5A9.5 9.5 0 1 0 1337.5 51.5"/><path d="M1337 36.5V42H1331.5"/><circle cx="1328" cy="45.5" r="2.3" fill="{WHITE}" stroke="none"/>'
               '<animateTransform attributeName="transform" type="rotate" from="0 1328 45.5" to="360 1328 45.5" dur="6s" repeatCount="indefinite"/></g>')
    out.append(ms.text(1348, 52, "Stick Tracking", 20, WHITE, "start", "", f"{FW600} {tl(123)}"))
    specs = (
        ("L", 1300, BLUE, "Left Stick", (1322, 292), (1396, 148), "M1402 168C1412 190 1392 210 1410 230L1432 240", -9),
        ("R", 1479, RED, "Right Stick", (1640, 292), (1580, 137), "M1573 152C1560 184 1538 190 1530 216C1524 230 1517 233 1515 240", 9),
    )
    for key, x0, col, head, base, tip, trail, kick in specs:
        w, h = 166, 210
        times = by_hand(hits, key)
        out.append(f'<clipPath id="cT{key}"><rect x="{x0}" y="68" width="{w}" height="{h}" rx="9"/></clipPath>')
        out.append(f'<g clip-path="url(#cT{key})"><rect x="{x0}" y="68" width="{w}" height="{h}" fill="#071225" fill-opacity=".88"/>'
                   f'<rect x="{x0 - 21}" y="68" width="{w + 42}" height="{h}" fill="url(#grid)"><animateTransform attributeName="transform" type="translate" values="0 0;21 0" dur="2.6s" repeatCount="indefinite"/></rect>'
                   f'<rect x="{x0}" y="68" width="{w}" height="35" fill="{col}" fill-opacity=".18"/><rect x="{x0}" y="102" width="{w}" height="1.6" fill="{col}"/>')
        px, py = base
        sway = (f'<animateTransform attributeName="transform" type="rotate" dur="3.2s" repeatCount="indefinite" calcMode="spline" keyTimes="0;.5;1" '
                f'values="-2.5 {px} {py};2.5 {px} {py};-2.5 {px} {py}" keySplines=".45 0 .55 1;.45 0 .55 1"/>')
        kt, vals = track(times, 0.42, f"{kick} {px} {py}", f"0 {px} {py}", f"0 {px} {py}")
        swing = f'<animateTransform attributeName="transform" type="rotate" additive="sum" dur="{CYCLE}s" repeatCount="indefinite" keyTimes="{kt}" values="{vals}"/>'
        if interactive:
            out.append(f'<g id="stick{key}" style="transform-box:view-box;transform-origin:{px}px {py}px">')
        out.append(f'<g>{sway}{swing}{wood_stick(base, tip, 18, 11, col, "wood" + key)}')
        theta = math.degrees(math.atan2(tip[1] - base[1], tip[0] - base[0])) + 90
        for frac in (0.30, 0.40):
            rx_, ry_ = base[0] + (tip[0] - base[0]) * frac, base[1] + (tip[1] - base[1]) * frac
            out.append(f'<ellipse cx="{f(rx_)}" cy="{f(ry_)}" rx="10" ry="3.8" transform="rotate({f(theta)} {f(rx_)} {f(ry_)})" fill="none" stroke="{col}" stroke-width="2.2"><animate attributeName="opacity" values="1;.35;1" dur="1.4s" repeatCount="indefinite"/></ellipse>')
        out.append(f'<circle cx="{tip[0]}" cy="{tip[1]}" r="9.5" fill="#0a1224" stroke="#fff" stroke-width="2.6"/>'
                   f'<circle cx="{tip[0]}" cy="{tip[1]}" r="9.5" fill="none" stroke="{col}" stroke-width="2" opacity="0"><animate attributeName="r" values="9.5;21" dur="1.5s" repeatCount="indefinite"/><animate attributeName="opacity" values=".9;0" dur="1.5s" repeatCount="indefinite"/></circle></g>')
        if interactive:
            out.append("</g>")
        out.append(f'<path d="{trail}" fill="none" stroke="{col}" stroke-width="1.8" stroke-linecap="round" stroke-dasharray="6 5"><animate attributeName="stroke-dashoffset" values="0;-22" dur="1.1s" repeatCount="indefinite"/></path></g>')
        out.append(f'<rect x="{x0 + .7}" y="68.7" width="{w - 1.4}" height="{h - 1.4}" rx="9" fill="none" stroke="{col}" stroke-opacity=".55" stroke-width="1.4"/>')
        out.append(ms.text(x0 + w / 2, 91.5, head, 18, col, "middle", "", FW600))
    return "".join(out)


def stats_panel(hits: dict[str, list[tuple[float, str]]]) -> str:
    out = [glass("gStats", 24, 100, 248, 168, 14)]
    rows = (("FPS", 127, MUTED, 30), ("Latency", 156, WHITE, 63), ("Sticks", 186, WHITE, 48), ("Left Hand", 216, WHITE, 77), ("Right Hand", 245, WHITE, 88))
    for label, y, colr, width in rows:
        out.append(ms.text(42, y + 6, label, 18, colr, "start", "", tl(width)))
    for val, y, width in (("30", 127, 21), ("28 ms", 156, 48)):
        out.append(f'<text x="162" y="{y + 6}" font-size="18" font-weight="700" fill="{GREEN}" filter="url(#gtxt)" {tl(width)} opacity="0">{val}<animate attributeName="opacity" values=".1;.8;.1" dur="2.4s" repeatCount="indefinite"/></text>')
        out.append(ms.text(162, y + 6, val, 18, GREEN, "start", "b", tl(width)))
    out.append(dot(167, 186, GREEN))
    out.append(ms.text(181, 192, "Detected", 18, WHITE, "start", "", tl(70)))
    out.append(dot(167, 216, BLUE, by_hand(hits, "L")))
    out.append(ms.text(181, 222, "Active", 18, WHITE, "start", "", tl(48)))
    out.append(dot(167, 245, "#ff3b4a", by_hand(hits, "R")))
    out.append(ms.text(181, 251, "Active", 18, WHITE, "start", "", tl(48)))
    return "".join(out)


def logo_card() -> str:
    out = [glass("gLogo", 18, 12, 284, 74, 14, 0.62)]
    beat = [round(b * BEAT, 3) for b in range(20)]
    out.append(f'<g fill="none" stroke="{WHITE}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
               '<ellipse cx="58" cy="47" rx="17" ry="5.6"/><path d="M41 47V60Q58 68.5 75 60V47"/><path d="M49 51.5V64M58 52.5V66M67 51.5V64" stroke-width="1.8" opacity=".85"/></g>')
    for x0, x1, sgn in ((42, 60, 1), (74, 56, -1)):
        times = [t for i, t in enumerate(beat) if (i % 2 == 0) == (sgn == 1)]
        kt, vals = track(times, 0.3, f"{-14 * sgn} {x0} 39", f"0 {x0} 39", f"0 {x0} 39")
        out.append(f'<g><animateTransform attributeName="transform" type="rotate" dur="{CYCLE}s" repeatCount="indefinite" keyTimes="{kt}" values="{vals}"/>'
                   f'<line x1="{x0}" y1="39" x2="{x1}" y2="25" stroke="{WHITE}" stroke-width="2.6" stroke-linecap="round"/><circle cx="{x1}" cy="25" r="2.2" fill="{WHITE}"/></g>')
    out.append(f'<text x="96" y="50" font-size="30" font-weight="800" fill="url(#shimmer)" {tl(176)}>SpaceDrums</text>')
    out.append(ms.text(96, 74, "AI Air Drumming", 18, MUTED, "start", "", tl(133)))
    return "".join(out)


def control_bar(interactive: bool = False) -> str:
    out = [f'<clipPath id="gBar"><rect x="0" y="848" width="{W}" height="93"/></clipPath>'
           f'<g clip-path="url(#gBar)"><use href="#blur"/><rect x="0" y="848" width="{W}" height="93" fill="#050a18" fill-opacity=".76"/></g>',
           '<rect x="0" y="847" width="1672" height="1.6" fill="#fff" fill-opacity=".16"/>']
    out.append('<rect x="18.7" y="861.7" width="174.6" height="60.6" rx="12" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".22" stroke-width="1.4"/>')
    out.append(f'<g>{gear(54, 892)}<animateTransform attributeName="transform" type="rotate" from="0 54 892" to="360 54 892" dur="24s" repeatCount="indefinite"/></g>')
    out.append(ms.text(85, 899, "Settings", 22, WHITE, "start", "", f"{FW500} {tl(75)}"))
    if interactive:
        out.append('<rect id="settingsHit" class="hit" x="18" y="861" width="175" height="61" rx="12" fill="#fff" fill-opacity="0" pointer-events="all"/>')
    out.append(ms.text(233, 871, "Camera View", 17, MUTED, "start", "", tl(101)))
    out.append('<rect x="231.7" y="880.7" width="240.6" height="41.6" rx="10" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".22" stroke-width="1.4"/>')
    out.append(f'<g fill="{WHITE}"><path d="M246 893.5h4l2-3h8l2 3h4a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3h-20a3 3 0 0 1-3-3v-12a3 3 0 0 1 3-3z"/><circle cx="256" cy="902.5" r="5.2" fill="#0b1426"/><circle cx="256" cy="902.5" r="3"/></g>')
    out.append(ms.text(280, 908, "Front (Default)", 19, WHITE, "start", "", f'id="camLabel" {tl(113)}' if interactive else tl(113)))
    if interactive:
        out.append('<rect id="camHit" class="hit" x="231" y="880" width="242" height="42" rx="10" fill="#fff" fill-opacity="0" pointer-events="all"/>')
    out.append(f'<path d="M446 897l7 7 7-7" fill="none" stroke="{WHITE}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><animateTransform attributeName="transform" type="translate" values="0 0;0 2.5;0 0" dur="2s" repeatCount="indefinite"/></path>')
    out.append('<rect x="788" y="868" width="378" height="62" rx="12" fill="#fff" fill-opacity=".035"/>')
    out.append(ms.text(797, 902, "Sensitivity", 20, WHITE, "start", "", tl(87)))
    out.append(slider(902, 1102, 895, 0.71, 1122, "0.7", "sens" if interactive else ""))
    out.append('<rect x="1290" y="868" width="372" height="62" rx="12" fill="#fff" fill-opacity=".035"/>')
    out.append(f'<path d="M1310 889h8l10-9v32l-10-9h-8z" fill="{WHITE}"/><path d="M1334 888q7 8 0 16M1339 882q12 14 0 28" fill="none" stroke="{WHITE}" stroke-width="2.4" stroke-linecap="round"><animate attributeName="opacity" values="1;.35;1" dur="1.2s" repeatCount="indefinite"/></path>')
    out.append(ms.text(1358, 902, "Volume", 20, WHITE, "start", "", tl(64)))
    out.append(slider(1445, 1598, 895, 0.79, 1614, "0.8", "vol" if interactive else ""))
    return "".join(out)


def concept_chip() -> str:
    return (f'<g>{ms.rect(696, 22, 280, 28, 14, "#05080f", GOLD, 1.5, FO55)}'
            f'<circle cx="716" cy="36" r="4" fill="{GOLD}"><animate attributeName="opacity" values="1;.25;1" dur="1.6s" repeatCount="indefinite"/></circle>'
            f'{ms.text(729, 40, "CONCEPT RENDER · NOT A SCREENSHOT", 11, GOLD, "start", "b", tl(232))}</g>')


# ----------------------------------------------------------------------------- assemble


def defs_markup(plate_uri: str, blur_uri: str) -> str:
    return f"""
<image id="plate" href="{plate_uri}" width="{W}" height="{H}"/>
<image id="blur" href="{blur_uri}" width="{W}" height="{H}" preserveAspectRatio="none"/>
<linearGradient id="slider" x1="0" x2="1"><stop offset="0" stop-color="#1b7dff"/><stop offset="1" stop-color="#34b4ff"/></linearGradient>
<linearGradient id="scan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5fd4ff" stop-opacity="0"/><stop offset=".85" stop-color="#5fd4ff" stop-opacity=".09"/><stop offset="1" stop-color="#bff0ff" stop-opacity=".34"/></linearGradient>
<linearGradient id="shimmer" gradientUnits="userSpaceOnUse" x1="96" y1="0" x2="272" y2="0" spreadMethod="repeat"><stop offset="0" stop-color="#ffffff"/><stop offset=".4" stop-color="#ffffff"/><stop offset=".5" stop-color="#8fe0ff"/><stop offset=".6" stop-color="#ffffff"/><stop offset="1" stop-color="#ffffff"/><animateTransform attributeName="gradientTransform" type="translate" values="-176 0;176 0" dur="5s" repeatCount="indefinite"/></linearGradient>
<pattern id="grid" width="21" height="21" patternUnits="userSpaceOnUse"><path d="M21 0H0V21" fill="none" stroke="#4aa0ff" stroke-opacity=".16" stroke-width="1"/></pattern>
<radialGradient id="vig" cx=".5" cy=".5" r=".75"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></radialGradient>
<filter id="neon" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="3.4"/></filter>
<filter id="gtxt" x="-40%" y="-60%" width="180%" height="220%"><feGaussianBlur stdDeviation="3.2"/></filter>
"""


CSS = ("@keyframes drift{0%{transform:translateY(0);opacity:0}15%{opacity:.85}85%{opacity:.6}100%{transform:translateY(-70px);opacity:0}}"
       ".dust{animation:drift 9s ease-in-out infinite;opacity:0}")


def build(photo_path: Path, debug: bool = False) -> str:
    plate_uri, blur_uri = images(photo_path)
    hits = groove()
    defs = defs_markup(plate_uri, blur_uri)
    body = ['<use href="#plate"/>', f'<rect width="{W}" height="{H}" fill="url(#vig)"/>']
    body += [pad_effects(hits), orbs_and_trails(hits), ar_layer(), labels(hits), tracking_panel(hits), stats_panel(hits), logo_card(), control_bar(), concept_chip()]
    if debug:
        for p in PADS.values():
            cx, cy = p["c"]
            body.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{p["rx"]}" ry="{p["ry"]}" transform="rotate({p["rot"]} {cx} {cy})" fill="none" stroke="#0ff" stroke-width="2"/>')
    return ms.svg(W, H, "SpaceDrums AR view (concept)",
                  "Concept render, not a screenshot: a player at a four-piece kit with glowing drums and sticks. The interface is redrawn as animated "
                  "vector UI: a logo card, a status panel, two stick-tracking views, drum labels and a control bar with camera, sensitivity and volume.",
                  "".join(body), defs, CSS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", type=Path, default=SRC)
    ap.add_argument("--debug", action="store_true", help="draw the pad ellipses on top")
    ap.add_argument("--output", type=Path, default=OUT)
    args = ap.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(args.photo, args.debug), encoding="utf-8", newline="\n")
    print(f"  {args.output}  {args.output.stat().st_size / 1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
