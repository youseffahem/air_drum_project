# ruff: noqa: E501  (SVG markup literals)
"""Write the animated SVGs of the README (hero, typing line, pipeline, concept figures, roadmap, ...).

    python scripts/make_readme_svgs.py                    # everything into docs/assets/readme/
    python scripts/make_readme_svgs.py --only hero        # one asset

The SVGs are self-contained (no scripts, no external fonts or images) so GitHub renders them inside an
``<img>``; the motion is SMIL and CSS only. They are **illustrations**: the concept figures state in the
picture that they are not data, and the one place that carries real numbers (the sample waveforms of the
kit figure) reads them from the recorded WAV files of the runtime bank. No measurement appears here.
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"

LS15 = 'letter-spacing="1.5"'
ITALIC = 'font-style="italic"'
INK, MUTED, DIM = "#e8ecf7", "#8f98b5", "#5a6488"
A, B, C, OK = "#46c8f5", "#fad250", "#ff6ed7", "#6ee05a"  # arm A / B / C colours of the project theme
CARD, CARD2, LINE = "#0f1630", "#151d3f", "#2a3358"
SANS = "'Segoe UI','SF Pro Display',Inter,system-ui,-apple-system,Roboto,'Helvetica Neue',Arial,sans-serif"
MONO = "ui-monospace,'SF Mono','Cascadia Mono',Consolas,Menlo,'DejaVu Sans Mono',monospace"

BASE_CSS = f"""
text{{font-family:{SANS}}}
.mono{{font-family:{MONO}}}
.b{{font-weight:700}} .bb{{font-weight:800}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg(w: int, h: int, title: str, desc: str, body: str, defs: str = "", css: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" '
        f'height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">\n'
        f'<title id="t">{esc(title)}</title>\n<desc id="d">{esc(desc)}</desc>\n'
        f"<defs>{defs}</defs>\n<style>{BASE_CSS}{css}</style>\n{body}\n</svg>\n"
    )


def f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def rect(x, y, w, h, rx=0, fill="none", stroke="", sw=1, extra="") -> str:
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(rx)}" fill="{fill}"{s} {extra}/>'


def text(x, y, s, size=14, fill=INK, anchor="start", cls="", extra="") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<text x="{f(x)}" y="{f(y)}" font-size="{f(size)}" fill="{fill}" text-anchor="{anchor}"{c} '
            f"{extra}>{esc(s)}</text>")


def appear(t0: float, cycle: float, hold: float | None = None, fade: float = 0.25, peak: float = 1.0) -> str:
    """Opacity animation inside a looping cycle: invisible, fades in at ``t0``, stays (until ``hold``, or the
    end of the cycle) and resets with the loop."""
    t_in, t_full = max(t0 - 0.001, 0) / cycle, min((t0 + fade) / cycle, 0.997)
    if hold is None:
        kt, vals = [0, t_in, t_full, 1], [0, 0, peak, peak]
    else:
        t_out = min(max(hold, t0 + fade) / cycle, 0.998)
        kt, vals = [0, t_in, t_full, t_out, min(t_out + fade / cycle, 0.999), 1], [0, 0, peak, peak, 0, 0]
    return (f'<animate attributeName="opacity" dur="{f(cycle)}s" repeatCount="indefinite" '
            f'keyTimes="{";".join(f(k) for k in kt)}" values="{";".join(f(v) for v in vals)}"/>')


def fade_in(t0: float, dur: float = 0.5) -> str:
    """One-shot fade-in that stays (for the first play of an animation)."""
    return (f'<animate attributeName="opacity" from="0" to="1" begin="{f(t0)}s" dur="{f(dur)}s" '
            'fill="freeze"/>')


def pulse(t0: float, cycle: float, span: float, attrs: dict[str, tuple[float, float]],
          opacity: float = 0.9) -> str:
    """A one-shot ring or flash inside a looping cycle: each attribute runs v0 -> v1 over ``span`` seconds
    from ``t0`` while the opacity fades out; before and after, the element is invisible."""
    t0c = t0 / cycle
    t1c = min((t0 + span) / cycle, 0.999)
    eps = 0.0005
    kt = f"0;{f(max(t0c - eps, 0))};{f(t0c)};{f(t1c)};1"
    out = [f'<animate attributeName="{a}" dur="{f(cycle)}s" repeatCount="indefinite" keyTimes="{kt}" '
           f'values="{f(v0)};{f(v0)};{f(v0)};{f(v1)};{f(v1)}"/>' for a, (v0, v1) in attrs.items()]
    out.append(f'<animate attributeName="opacity" dur="{f(cycle)}s" repeatCount="indefinite" keyTimes="{kt}" '
               f'values="0;0;{f(opacity)};0;0"/>')
    return "".join(out)


def stars(n: int, w: int, h: int, seed: int, rmax: float = 1.7, ymax: float | None = None) -> str:
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        x, y = rnd.uniform(8, w - 8), rnd.uniform(8, (ymax or h) - 8)
        r = rnd.choice([0.6, 0.8, 1.0, 1.2, rmax])
        d, k = rnd.uniform(2.2, 5.5), rnd.uniform(0, 6)
        col = rnd.choice(["#ffffff", "#bfe9ff", "#ffd6f5", "#fff2c2"])
        out.append(f'<circle class="s" cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{col}" '
                   f'style="animation-duration:{f(d)}s;animation-delay:-{f(k)}s"/>')
    return "".join(out)


STAR_CSS = "@keyframes tw{0%,100%{opacity:.18}50%{opacity:1}} .s{animation:tw 3s ease-in-out infinite;opacity:.4}"


def keyed_translate(points: list[tuple[float, float, float, str]], cycle: float) -> str:
    """SMIL translate through (t, x, y, ease) waypoints with spline easing; ``ease`` shapes the segment
    that *ends* at the waypoint (in = accelerate, out = decelerate, io = smooth)."""
    splines = {"in": "0.55 0 1 0.45", "out": "0 0.55 0.45 1", "io": "0.45 0 0.55 1"}
    kt = ";".join(f(p[0] / cycle) for p in points)
    vals = ";".join(f"{f(p[1])} {f(p[2])}" for p in points)
    ks = ";".join(splines[p[3]] for p in points[1:])
    return (f'<animateTransform attributeName="transform" type="translate" dur="{f(cycle)}s" '
            f'repeatCount="indefinite" calcMode="spline" keyTimes="{kt}" values="{vals}" keySplines="{ks}"/>')


# ----------------------------------------------------------------------------- hero


def stick_waypoints(hits: list[tuple[float, int]], pads: dict[int, tuple[float, float]], cycle: float,
                    raise_px: float, down: float = 0.20, rise: float = 0.22):
    """(t, x, y, ease) for one stick: raised above each pad, strike at ``t``, rebound, travel to the next.
    ``pads[i]`` = (x centre, y of the top edge). Moves between pads in the same column go around."""
    pts: list[tuple[float, float, float, str]] = []
    first = pads[hits[0][1]]
    pts.append((0.0, first[0], first[1] - raise_px, "io"))
    prev = None
    for t, pad in hits:
        x, y = pads[pad]
        if prev is not None:
            px, py = prev
            t_ready = t - down
            if abs(px - x) < 1 and y > py:  # the next pad lies below: go around outwards
                side = 1 if x > 640 else -1
                mid_t = (pts[-1][0] + t_ready) / 2
                pts.append((mid_t, x + side * 150, (py + y) / 2 - raise_px * 0.4, "io"))
            pts.append((t_ready, x, y - raise_px, "io"))
        pts.append((t, x, y + 6, "in"))
        pts.append((t + rise, x, y - raise_px * 0.85, "out"))
        prev = (x, y)
    pts.append((cycle, first[0], first[1] - raise_px, "io"))
    return pts


def hero() -> str:
    w, h, cycle = 1280, 480, 6.0
    pad_w, pad_h = 224, 92
    cols, rows = (668, 968), (150, 292)
    names = {0: "CRASH / RIDE", 1: "HI-HAT", 2: "SNARE", 3: "TOM 1"}
    metal = {0: "brass", 1: "brass", 2: "silver", 3: "silver"}
    glow = {0: B, 1: A, 2: C, 3: OK}
    pos = {i: (cols[i % 2], rows[i // 2]) for i in range(4)}
    pads_top = {i: (pos[i][0] + pad_w / 2, pos[i][1] + 14) for i in range(4)}
    # Two sticks. Display-left hand: crash, snare; display-right hand: hi-hat, tom 1 (indices into pads).
    left_hits = [(0.55, 0), (1.55, 2), (2.15, 2), (3.35, 0), (4.55, 2), (5.15, 2)]
    right_hits = [(0.55, 1), (1.15, 1), (2.35, 3), (2.95, 3), (4.15, 1), (4.75, 3)]
    body = []
    body.append(rect(0, 0, w, h, 24, "url(#bg)"))
    body.append(rect(0, 0, w, h, 24, "url(#gA)"))
    body.append(rect(0, 0, w, h, 24, "url(#gB)"))
    body.append(f'<g clip-path="url(#round)">{stars(78, w, h, 11, ymax=h - 40)}')
    for x, y, d in [(1180, 20, 0), (900, 10, 3.6), (1230, 140, 7.2)]:
        body.append(f'<g class="sh" style="animation-delay:-{f(d)}s"><line x1="{x}" y1="{y}" x2="{x + 70}" '
                    f'y2="{y - 40}" stroke="url(#trail)" stroke-width="2" stroke-linecap="round"/></g>')
    # floor glow under the kit
    body.append('<ellipse cx="934" cy="440" rx="420" ry="26" fill="url(#floor)"/>')
    # pads
    for i in range(4):
        x, y = pos[i]
        body.append(f'<g transform="translate({x} {y})">')
        body.append(rect(0, 0, pad_w, pad_h, 14, "#2c3146", "#cfd3df", 2))
        body.append(rect(4, 4, pad_w - 8, pad_h - 8, 11, "#3b4158"))
        body.append(f'<ellipse cx="{pad_w / 2}" cy="{pad_h / 2}" rx="{pad_w / 2 - 22}" ry="{pad_h / 2 - 14}" '
                    f'fill="url(#{metal[i]})" stroke="#e9e3d2" stroke-opacity=".7"/>')
        if metal[i] == "brass":
            body.append(f'<ellipse cx="{pad_w / 2}" cy="{pad_h / 2}" rx="20" ry="9" fill="#c9a24c" stroke="#8a6420"/>')
            body.append(f'<circle cx="{pad_w / 2}" cy="{pad_h / 2}" r="3" fill="#3a2d12"/>')
        body.append('<line x1="18" y1="14" x2="206" y2="14" stroke="#ffe27a" stroke-width="3" stroke-linecap="round" '
                    'stroke-opacity=".9"/>')
        flashes = [t for t, p in left_hits + right_hits if p == i]
        for t in flashes:
            body.append(f'<ellipse cx="{pad_w / 2}" cy="{pad_h / 2}" rx="{pad_w / 2 - 22}" ry="{pad_h / 2 - 14}" '
                        f'fill="{glow[i]}" opacity="0">{pulse(t, cycle, 0.45, {}, 0.5)}</ellipse>')
            body.append(f'<ellipse cx="{pad_w / 2}" cy="14" rx="10" ry="4" fill="none" stroke="{glow[i]}" '
                        f'stroke-width="3" opacity="0">'
                        f'{pulse(t, cycle, 0.9, {"rx": (10, 150), "ry": (4, 54)}, 0.85)}</ellipse>')
        body.append(text(pad_w / 2, pad_h + 20, names[i], 12, MUTED, "middle", "b", 'letter-spacing="2"'))
        body.append("</g>")
    # sticks
    for hits, tint in ((left_hits, "#ffd9a0"), (right_hits, "#ffe9c4")):
        pts = stick_waypoints(hits, pads_top, cycle, 66)
        body.append(f'<g>{keyed_translate(pts, cycle)}')
        body.append('<line x1="0" y1="-84" x2="0" y2="0" stroke="#12141f" stroke-width="9" stroke-linecap="round"/>')
        body.append(f'<line x1="0" y1="-84" x2="0" y2="0" stroke="{tint}" stroke-width="5" stroke-linecap="round"/>')
        body.append('<circle cx="0" cy="-86" r="11" fill="#b58a73" stroke="#7b5646" stroke-width="2"/>')
        body.append(f'<circle cx="0" cy="0" r="12" fill="none" stroke="{A}" stroke-width="2" stroke-dasharray="4 5" '
                    'opacity=".9"><animateTransform attributeName="transform" type="rotate" from="0 0 0" '
                    'to="360 0 0" dur="3s" repeatCount="indefinite"/></circle>')
        body.append('<circle cx="0" cy="0" r="3.5" fill="#ffffff"/></g>')
    body.append("</g>")
    # title block
    body.append(text(72, 74, "GRADUATION PROJECT   ·   COMPUTER VISION   ·   CAUSAL PREDICTION", 13, A, "start",
                     "b", 'letter-spacing="3"'))
    for y, word in ((176, "SPACE"), (280, "DRUMS")):
        body.append(f'<text x="72" y="{y}" font-size="116" class="bb" fill="{C}" opacity=".55" filter="url(#blur)" '
                    f'textLength="{ 470 if word == "SPACE" else 480}" lengthAdjust="spacingAndGlyphs">{word}</text>')
        body.append(f'<text x="72" y="{y}" font-size="116" class="bb" fill="url(#title)" '
                    f'textLength="{ 470 if word == "SPACE" else 480}" lengthAdjust="spacingAndGlyphs">{word}</text>')
    body.append(text(74, 330, "Play a drum kit in mid-air.", 29, INK, "start", "b"))
    body.append(text(74, 362, "Ordinary sticks. One webcam. Causal strike anticipation.", 17, MUTED))
    chips = ["1 webcam", "2 sticks", "0 sensors", "100 % offline"]
    x = 74
    for k, label in enumerate(chips):
        cw = 14 * len(label) * 0.62 + 30
        body.append(f'<g opacity="0">{rect(x, 384, cw, 30, 15, "#0e1530", LINE, 1.5)}'
                    f'{text(x + cw / 2, 404, label, 13, INK, "middle", "b")}'
                    f'{fade_in(0.3 + k * 0.25, 0.5)}</g>')
        x += cw + 12
    # equaliser
    rnd = random.Random(5)
    bars = []
    for k in range(64):
        bx = 72 + k * 18.1
        hgt = rnd.uniform(10, 24)
        bars.append(f'<rect class="eq" x="{f(bx)}" y="{f(462 - hgt)}" width="10" height="{f(hgt)}" rx="3" '
                    f'fill="url(#eqg)" style="animation-duration:{f(rnd.uniform(0.7, 1.9))}s;'
                    f'animation-delay:-{f(rnd.uniform(0, 2))}s"/>')
    body.append("".join(bars))
    body.append(rect(1, 1, w - 2, h - 2, 23, "none", "url(#edge)", 2))
    defs = f"""
<clipPath id="round"><rect width="{w}" height="{h}" rx="24"/></clipPath>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#060a1b"/><stop offset=".55" stop-color="#120c30"/><stop offset="1" stop-color="#08122a"/></linearGradient>
<radialGradient id="gA" cx=".78" cy=".55" r=".5"><stop offset="0" stop-color="{A}" stop-opacity=".30"/><stop offset="1" stop-color="{A}" stop-opacity="0"/></radialGradient>
<radialGradient id="gB" cx=".1" cy=".05" r=".6"><stop offset="0" stop-color="{C}" stop-opacity=".22"/><stop offset="1" stop-color="{C}" stop-opacity="0"/></radialGradient>
<linearGradient id="title" gradientUnits="userSpaceOnUse" x1="72" y1="0" x2="552" y2="0" spreadMethod="repeat">
 <stop offset="0" stop-color="#7be0ff"/><stop offset=".33" stop-color="#9b8cff"/><stop offset=".5" stop-color="#ff7ee0"/><stop offset=".66" stop-color="#9b8cff"/><stop offset="1" stop-color="#7be0ff"/>
 <animateTransform attributeName="gradientTransform" type="translate" values="0 0;480 0" dur="6s" repeatCount="indefinite"/>
</linearGradient>
<radialGradient id="brass" cx=".5" cy=".4" r=".75"><stop offset="0" stop-color="#f6e3a1"/><stop offset=".5" stop-color="#d4a94a"/><stop offset="1" stop-color="#7d5a1f"/></radialGradient>
<radialGradient id="silver" cx=".5" cy=".4" r=".75"><stop offset="0" stop-color="#fbfcff"/><stop offset=".55" stop-color="#b9c0cd"/><stop offset="1" stop-color="#6b7388"/></radialGradient>
<radialGradient id="floor" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{A}" stop-opacity=".25"/><stop offset="1" stop-color="{A}" stop-opacity="0"/></radialGradient>
<linearGradient id="trail" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff"/></linearGradient>
<linearGradient id="eqg" gradientUnits="userSpaceOnUse" x1="72" y1="0" x2="1208" y2="0"><stop offset="0" stop-color="{A}"/><stop offset=".5" stop-color="#9b8cff"/><stop offset="1" stop-color="{C}"/></linearGradient>
<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{A}" stop-opacity=".55"/><stop offset=".5" stop-color="#9b8cff" stop-opacity=".15"/><stop offset="1" stop-color="{C}" stop-opacity=".55"/></linearGradient>
<filter id="blur" x="-10%" y="-20%" width="120%" height="140%"><feGaussianBlur stdDeviation="9"/></filter>
"""
    css = STAR_CSS + """
@keyframes eq{0%,100%{transform:scaleY(.22)}50%{transform:scaleY(1)}}
.eq{transform-box:fill-box;transform-origin:50% 100%;animation:eq 1.2s ease-in-out infinite;opacity:.85}
@keyframes shoot{0%{transform:translate(0,0);opacity:0}3%{opacity:1}16%{transform:translate(-420px,235px);opacity:0}100%{transform:translate(-420px,235px);opacity:0}}
.sh{animation:shoot 10.8s linear infinite;opacity:0}
"""
    return svg(w, h, "Space Drums", "Animated banner: two drumsticks play a four-pad virtual drum kit under a "
               "starfield; the title reads Space Drums, play a drum kit in mid-air with ordinary sticks and "
               "one webcam.", "".join(body), defs, css)


# ----------------------------------------------------------------------------- typing line


def typing() -> str:
    w, h = 920, 52
    phrases = [
        "Track ordinary drumsticks with a single webcam",
        "Anticipate strikes from causal stick motion",
        "Commit once per strike, then schedule the sample",
        "Run offline. Measure everything. Fabricate nothing.",
    ]
    cw, x0 = 12.0, 54.0
    each, type_s, hold_s, del_s = 4.6, 1.7, 1.7, 0.5
    cycle = each * len(phrases)
    body = [rect(0.5, 0.5, w - 1, h - 1, 26, "#0b1024", LINE, 1.5),
            text(26, 34, "›", 22, A, "start", "mono b")]
    clips = []
    for i, ph in enumerate(phrases):
        n = len(ph)
        start = i * each
        kt, widths = [0.0], [0.0]
        for k in range(1, n + 1):
            kt.append((start + type_s * k / n) / cycle)
            widths.append(k * cw)
        del_start = start + type_s + hold_s
        for k in range(n - 1, -1, -1):
            kt.append((del_start + del_s * (n - k) / n) / cycle)
            widths.append(k * cw)
        key = ";".join(f(v) for v in kt)
        clips.append(f'<clipPath id="c{i}"><rect x="{x0}" y="0" width="0" height="{h}">'
                     f'<animate attributeName="width" dur="{f(cycle)}s" repeatCount="indefinite" calcMode="discrete" '
                     f'keyTimes="{key}" values="{";".join(f(v) for v in widths)}"/></rect></clipPath>')
        body.append(f'<g clip-path="url(#c{i})"><text class="mono" x="{x0}" y="33" font-size="20" fill="{INK}" '
                    f'textLength="{f(n * cw)}" lengthAdjust="spacing" xml:space="preserve">{esc(ph)}</text></g>')
        cur_x = ";".join(f(x0 + v) for v in widths)
        visible = f'<animate attributeName="opacity" dur="{f(cycle)}s" repeatCount="indefinite" calcMode="discrete" ' \
                  f'keyTimes="0;{f(start / cycle)};{f((del_start + del_s + 0.15) / cycle)}" values="0;1;0"/>'
        body.append(f'<g opacity="0">{visible}<rect x="{x0}" y="13" width="2.5" height="26" rx="1" fill="{A}">'
                    f'<animate attributeName="x" dur="{f(cycle)}s" repeatCount="indefinite" calcMode="discrete" '
                    f'keyTimes="{key}" values="{cur_x}"/>'
                    f'<animate attributeName="opacity" dur="0.9s" repeatCount="indefinite" calcMode="discrete" '
                    f'keyTimes="0;.6" values="1;0.15"/></rect></g>')
    return svg(w, h, "Space Drums tagline", "Typewriter line cycling through four short descriptions of the "
               "project.", "".join(body), "".join(clips))


# ----------------------------------------------------------------------------- divider


def divider() -> str:
    w, h = 1240, 28
    period = 62
    d = "M0 14 " + "".join(f"q{period / 4} -11 {period / 2} 0 t{period / 2} 0 " for _ in range(w // period + 3))
    defs = (f'<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="0" x2="{w}" y1="0" y2="0">'
            f'<stop offset="0" stop-color="{A}"/><stop offset=".5" stop-color="#9b8cff"/>'
            f'<stop offset="1" stop-color="{C}"/></linearGradient>'
            f'<linearGradient id="m" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            f'<stop offset=".18" stop-color="#fff"/><stop offset=".82" stop-color="#fff"/>'
            f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<mask id="k"><rect width="{w}" height="{h}" fill="url(#m)"/></mask>')
    body = (f'<g mask="url(#k)"><path d="{d}" fill="none" stroke="url(#g)" stroke-width="2.2" '
            f'stroke-linecap="round" opacity=".85"><animateTransform attributeName="transform" type="translate" '
            f'from="0 0" to="-{period} 0" dur="2.4s" repeatCount="indefinite"/></path>'
            f'<path d="{d}" fill="none" stroke="url(#g)" stroke-width="1" opacity=".35" '
            f'transform="translate(-{period / 2} 0)"><animateTransform attributeName="transform" type="translate" '
            f'from="-{period / 2} 3" to="-{period * 1.5} 3" dur="3.6s" repeatCount="indefinite"/></path></g>')
    return svg(w, h, "Divider", "Decorative animated sound-wave divider.", body, defs)


# ----------------------------------------------------------------------------- pipeline

OP85 = 'opacity=".85"'
DASHED = 'stroke-dasharray="6 6" opacity=".7"'
GROUP = {"perception": A, "state": "#9b8cff", "anticipation": B, "decision": OK, "output": C}

ICONS = {
    "camera": '<rect x="4" y="10" width="26" height="18" rx="4"/><circle cx="17" cy="19" r="5.5"/><rect x="11" y="5" width="12" height="5" rx="1.5"/>',
    "hand": '<circle cx="17" cy="23" r="7"/><path d="M11 19 8 8M14 16 13 5M17 15V4M20 16l1-11M24 19l3-10"/>',
    "stick": '<path d="M6 29 27 8" stroke-width="4"/><circle cx="28" cy="7" r="3.5" fill="currentColor"/>',
    "tracking": '<circle cx="17" cy="17" r="9"/><path d="M17 2v6M17 26v6M2 17h6M26 17h6"/><circle cx="17" cy="17" r="2" fill="currentColor"/>',
    "features": '<rect x="6" y="17" width="5" height="13" rx="1.5"/><rect x="14" y="8" width="5" height="22" rx="1.5"/><rect x="22" y="13" width="5" height="17" rx="1.5"/>',
    "prediction": '<path d="M4 29C10 27 14 21 18 15"/><path d="M18 15C22 9 26 7 31 5" stroke-dasharray="3 3.5"/><circle cx="18" cy="15" r="2.5" fill="currentColor"/>',
    "geometry": '<rect x="5" y="16" width="24" height="14" rx="5"/><path d="M8 16h18" stroke-width="3.5"/><path d="M17 3v9M13 9l4 4 4-4"/>',
    "commit": '<circle cx="17" cy="17" r="12.5"/><path d="M10 17.5l5 5 9-10.5"/>',
    "audio": '<path d="M5 13h6l7-6v20l-7-6H5z"/><path d="M22 12q4 5 0 10M25 8q8 9 0 18"/>',
}


def icon(kind: str, x: float, y: float, col: str) -> str:
    return (f'<g transform="translate({f(x)} {f(y)})" fill="none" stroke="{col}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round" color="{col}">{ICONS[kind]}</g>')


def wrap(s: str, width: int) -> list[str]:
    line, lines = "", []
    for word in s.split():
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*lines, line]


def pipeline() -> str:
    w, h, cycle = 1240, 560, 15.0
    nw, nh = 206, 138
    stages = [
        ("CAPTURE", "perception", "camera", ("Timestamped frames,", "fixed playing ROI"), "FrameSample"),
        ("HANDS", "perception", "hand", ("21 landmarks per hand,", "LEFT / RIGHT identity"), "HandObservation"),
        ("STICK", "perception", "stick", ("Stick axis and visible", "endpoint estimate"), "StickObservation"),
        ("TRACKING", "state", "tracking", ("Per-hand causal filter", "and state machine"), "TrackState"),
        ("FEATURES", "state", "features", ("Causal kinematics from", "bounded history"), "KinematicFeatures"),
        ("PREDICTION", "anticipation", "prediction", ("Observed path (A) or", "predicted path (B, C)"), "TrajectoryPrediction"),
        ("GEOMETRY", "decision", "geometry", ("Zones, impact surface,", "sub-frame crossing"), "StrikeCandidate"),
        ("COMMIT", "decision", "commit", ("One commit per entry;", "refractory, de-dup"), "CommittedStrike"),
        ("AUDIO", "output", "audio", ("Recorded samples,", "time-targeted mixer"), "AudioEvent"),
    ]

    def x_of(i: int) -> float:
        return 29 + (i % 5) * 244

    def y_of(i: int) -> float:
        return 70 if i < 5 else 276

    centers = [(x_of(i) + nw / 2, y_of(i) + nh / 2) for i in range(9)]
    cap = (x_of(4) + nw / 2, y_of(5) + nh / 2)  # the speaker sits in the fifth slot of row 2
    turn_y = (y_of(0) + nh + y_of(5)) / 2
    c4, c5 = centers[4], centers[5]
    path = (f"M{f(centers[0][0])} {f(centers[0][1])} L{f(c4[0])} {f(c4[1])} L{f(c4[0])} {f(turn_y - 18)} "
            f"Q{f(c4[0])} {f(turn_y)} {f(c4[0] - 18)} {f(turn_y)} L{f(c5[0] + 18)} {f(turn_y)} "
            f"Q{f(c5[0])} {f(turn_y)} {f(c5[0])} {f(turn_y + 18)} L{f(c5[0])} {f(c5[1])} L{f(cap[0])} {f(cap[1])}")
    turn = (turn_y - c4[1]) + (c4[0] - c5[0]) + (c5[1] - turn_y)
    at = {i: i * 244.0 for i in range(5)} | {5 + j: 4 * 244.0 + turn + j * 244.0 for j in range(4)}
    total = 4 * 244.0 + turn + 4 * 244.0
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(46, w, h, 21)}</g>']
    body.append(text(29, 40, "DATA FLOW  ·  ONE RECORD TYPE PER STAGE", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    body.append(f'<path d="{path}" fill="none" stroke="{LINE}" stroke-width="3" stroke-linecap="round" stroke-dasharray="2 8"/>')
    for i in range(9):
        if i == 4:
            continue
        cx, cy = x_of(i) + nw + 19, y_of(i) + nh / 2
        body.append(f'<path d="M{f(cx - 5)} {f(cy - 7)}L{f(cx + 5)} {f(cy)}L{f(cx - 5)} {f(cy + 7)}" fill="none" stroke="{DIM}" '
                    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')
    for i, (name, grp, ic, desc, out) in enumerate(stages):
        x, y, col = x_of(i), y_of(i), GROUP[grp]
        body.append(f'<g>{rect(x, y, nw, nh, 16, "#0f1630", LINE, 1.6)}{rect(x + 1, y + 1, nw - 2, 5, 3, col, "", 0, OP85)}')
        body.append(f'<rect x="{x - 3}" y="{y - 3}" width="{nw + 6}" height="{nh + 6}" rx="19" fill="none" stroke="{col}" '
                    f'stroke-width="3" opacity="0">{pulse(at[i] / total * cycle, cycle, 1.0, {}, 0.9)}</rect>')
        body.append(f'<circle cx="{x + 24}" cy="{y + 33}" r="12" fill="{col}" fill-opacity=".16" stroke="{col}" stroke-width="1.5"/>')
        body.append(text(x + 24, y + 37.5, f"{i + 1}", 12.5, col, "middle", "b"))
        body.append(text(x + 44, y + 38, name, 15.5, INK, "start", "bb", 'letter-spacing="1.6"'))
        body.append(icon(ic, x + nw - 50, y + 14, col))
        body.append(text(x + 18, y + 66, desc[0], 12.5, MUTED))
        body.append(text(x + 18, y + 83, desc[1], 12.5, MUTED))
        if i == 5:
            for k, (lab, c2) in enumerate((("A reactive", A), ("B rule", B), ("C learned", C))):
                bx = x + 18 + k * 62
                body.append(rect(bx, y + 91, 58, 17, 8.5, "none", c2, 1.3))
                body.append(text(bx + 29, y + 103, lab, 9.5, c2, "middle", "b"))
        body.append(text(x + 18, y + nh - 12, "→ " + out, 11.5, col, "start", "mono b"))
        body.append("</g>")
    capx = x_of(4)
    body.append(f'<g>{rect(capx, y_of(5), nw, nh, 16, "none", C, 1.6, DASHED)}'
                f'{icon("audio", capx + nw / 2 - 17, y_of(5) + 30, C)}'
                f'{text(capx + nw / 2, y_of(5) + 92, "drum sound", 16, INK, "middle", "bb")}'
                f'{text(capx + nw / 2, y_of(5) + 112, "from the speakers", 12, MUTED, "middle")}</g>')
    for k, (r, op) in enumerate(((6.5, 1.0), (5, 0.6), (3.8, 0.38), (2.8, 0.2))):
        body.append(f'<circle r="{r}" fill="#ffffff" opacity="{op}" filter="url(#dot)"><animateMotion dur="{cycle}s" '
                    f'begin="-{f(k * 0.13)}s" repeatCount="indefinite" path="{path}"/></circle>')
    notes = [
        ("One monotonic clock", "Every record carries the t_capture of the frame it came from (ADR-0004)."),
        ("Causal by construction", "Components consume only observations with timestamp ≤ now; TEST-CAUSAL-1/2 check it."),
        ("One geometry, one commit policy", "Arms A, B and C share the same geometry and commit code (ADR-0008)."),
    ]
    for k, (head, tail) in enumerate(notes):
        x = 29 + k * 404
        body.append(rect(x, 464, 382, 72, 14, "#0c1229", LINE, 1.2))
        body.append(text(x + 18, 490, head, 14, INK, "start", "b"))
        for j, ln in enumerate(wrap(tail, 56)[:2]):
            body.append(text(x + 18, 510 + j * 16, ln, 12, MUTED))
    defs = """
<clipPath id="round"><rect width="1240" height="560" rx="24"/></clipPath>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#060a1b"/><stop offset=".6" stop-color="#0e0c2a"/><stop offset="1" stop-color="#08122a"/></linearGradient>
<filter id="dot" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
"""
    return svg(w, h, "Space Drums pipeline", "Animated data-flow diagram: capture, hands, stick, tracking, features, "
               "prediction, geometry, commit and audio, each producing one record type; a light packet travels the "
               "whole chain.", "".join(body), defs, STAR_CSS)


# ----------------------------------------------------------------------------- concept: anticipation

BG_DEFS = """
<clipPath id="round"><rect width="{w}" height="{h}" rx="24"/></clipPath>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#060a1b"/><stop offset=".6" stop-color="#0e0c2a"/><stop offset="1" stop-color="#08122a"/></linearGradient>
"""


def tip_curve(x0: float, x_hit: float, y_s: float, drop: float, x1: float, step: float = 10.0):
    """Illustrative tip height over time: accelerating descent to the surface at ``x_hit``, a short overshoot,
    a rebound and a hover. Returns [(x, y)] (screen coordinates, y down)."""
    pts = []
    x = x0
    while x <= x1 + 0.01:
        if x <= x_hit:
            u = (x - x0) / (x_hit - x0)
            y = y_s - drop * (1 - u ** 2.2)
        elif x <= x_hit + 58:
            y = y_s + 16 * math.sin(math.pi * (x - x_hit) / 58)
        elif x <= x_hit + 200:
            u = (x - x_hit - 58) / 142
            y = y_s - 84 * (1 - (1 - u) ** 2)
        else:
            y = y_s - 84
        pts.append((x, y))
        x += step
    return pts


def concept_anticipation() -> str:
    w, h, cycle = 1160, 596, 12.0
    x_lo, x_hi, x_imp = 300.0, 1110.0, 760.0
    t_a, t_b = 0.8, 9.2  # the playhead crosses the plot between these times

    def t_at(x: float) -> float:
        return t_a + (x - x_lo) / (x_hi - x_lo) * (t_b - t_a)

    lanes = [("ARM A  ·  REACTIVE", ("Commit once the crossing", "has been observed."), A, 70.0, 0),
             ("ARMS B / C  ·  ANTICIPATORY", ("Commit before the predicted", "crossing, from motion so far."), B, 310.0, 1)]
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(40, w, h, 33)}</g>']
    body.append(text(36, 40, "CONCEPT  ·  WHEN DOES THE COMMIT HAPPEN?", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    body.append(f'<g>{rect(w - 330, 22, 294, 26, 13, "none", B, 1.4)}{text(w - 183, 40, "ILLUSTRATIVE  ·  NOT MEASURED DATA", 11, B, "middle", "b", LS15)}</g>')
    clips = []
    for title, sub, col, y0, kind in lanes:
        y_s = y0 + 112
        body.append(rect(24, y0, w - 48, 222, 18, "#0d1330", LINE, 1.2))
        body.append(text(48, y0 + 40, title, 15, col, "start", "bb", 'letter-spacing="1.5"'))
        body.append(text(48, y0 + 64, sub[0], 12.5, MUTED))
        body.append(text(48, y0 + 81, sub[1], 12.5, MUTED))
        body.append(f'<line x1="{x_lo}" y1="{y_s}" x2="{x_hi}" y2="{y_s}" stroke="{A}" stroke-width="2" stroke-dasharray="7 6" opacity=".55"/>')
        body.append(text(x_hi - 4, y_s - 8, "impact surface", 11, A, "end", "mono", 'opacity=".8"'))
        curve = tip_curve(x_lo + 10, x_imp, y_s, 96, x_hi)
        d = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in curve)
        body.append(f'<path d="{d}" fill="none" stroke="{DIM}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity=".7"/>')
        clips.append(f'<clipPath id="r{kind}"><rect x="{x_lo}" y="{y0}" width="0" height="222">'
                     f'<animate attributeName="width" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;{f(t_a / cycle)};{f(t_b / cycle)};1" '
                     f'values="0;0;{f(x_hi - x_lo)};{f(x_hi - x_lo)}"/></rect></clipPath>')
        body.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" clip-path="url(#r{kind})"/>')
        # the moving tip
        kt = [0.0, t_a / cycle] + [t_at(x) / cycle for x, _ in curve[1:]] + [1.0]
        xs = [curve[0][0], curve[0][0]] + [x for x, _ in curve[1:]] + [curve[-1][0]]
        ys = [curve[0][1], curve[0][1]] + [y for _, y in curve[1:]] + [curve[-1][1]]
        kts = ";".join(f(k) for k in kt)
        body.append(f'<circle r="7" fill="{col}" stroke="#fff" stroke-width="2"><animate attributeName="cx" dur="{cycle}s" repeatCount="indefinite" '
                    f'keyTimes="{kts}" values="{";".join(f(v) for v in xs)}"/><animate attributeName="cy" dur="{cycle}s" repeatCount="indefinite" '
                    f'keyTimes="{kts}" values="{";".join(f(v) for v in ys)}"/></circle>')
        if kind == 0:
            segs = [(0, 36, "#7a86b8"), (36, 44, "#9b8cff"), (80, 14, OK), (94, 78, C)]
            for s0, sl, sc in segs:
                body.append(f'<g>{rect(x_imp + s0, y_s + 30, sl, 12, 3, sc)}{appear(t_at(x_imp + s0 + sl) + 0.0, cycle, cycle - 0.5, 0.3)}</g>')
            commit_x, sound_x = x_imp + 94, x_imp + 172
            body.append(f'<g>{pin(commit_x, y_s + 52, OK, "commit")}{appear(t_at(commit_x), cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g>{pin(sound_x, y_s + 52, C, "sound")}{appear(t_at(sound_x), cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g>{bracket(x_imp, sound_x, y_s + 78, "L_sys", MUTED)}{appear(t_at(sound_x) + 0.1, cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g>{text(x_imp - 8, y_s + 20, "observed after the fact", 11, MUTED, "end", "", ITALIC)}{appear(t_at(x_imp), cycle, cycle - 0.5, 0.3)}</g>')
        else:
            pred_x, commit_x, sound_x = 530.0, 614.0, 836.0
            i0 = min(range(len(curve)), key=lambda i: abs(curve[i][0] - pred_x))
            fut = [(x, y) for x, y in curve if pred_x <= x <= x_imp + 14]
            dd = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in fut)
            body.append(f'<path d="{dd}" fill="none" stroke="{B}" stroke-width="3" stroke-dasharray="3 6" stroke-linecap="round" opacity=".95">'
                        f'{appear(t_at(pred_x), cycle, t_at(x_imp), 0.4, 0.95)}</path>')
            body.append(f'<g>{pin(pred_x, y_s + 52, B, "prediction", "left")}{appear(t_at(pred_x), cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g>{pin(commit_x, y_s + 52, OK, "commit", "right")}{appear(t_at(commit_x), cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g>{bracket(commit_x, x_imp, y_s + 78, "L_pred", B)}{appear(t_at(x_imp), cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g>{pin(sound_x, y_s + 52, C, "sound")}{appear(t_at(sound_x), cycle, cycle - 0.5, 0.3)}</g>')
            body.append(f'<g><line x1="{commit_x}" y1="{y_s + 52}" x2="{sound_x}" y2="{y_s + 52}" stroke="{DIM}" stroke-width="1.6" stroke-dasharray="2 5"/>'
                        f'{text(sound_x + 14, y_s + 82, "audio scheduling and output latency still apply", 10.5, MUTED, "start")}'
                        f'{appear(t_at(sound_x), cycle, cycle - 0.5, 0.3)}</g>')
            _ = i0
    # shared impact line and playhead
    body.append(f'<line x1="{x_imp}" y1="64" x2="{x_imp}" y2="540" stroke="#ffffff" stroke-width="1.6" stroke-dasharray="3 5" opacity=".55"/>')
    body.append(text(x_imp, 62, "estimated impact", 11, "#ffffff", "middle", "mono", 'opacity=".8"'))
    body.append(f'<line y1="70" y2="540" stroke="#fff" stroke-width="2" opacity="0"><animate attributeName="x1" dur="{cycle}s" repeatCount="indefinite" '
                f'keyTimes="0;{f(t_a / cycle)};{f(t_b / cycle)};1" values="{x_lo};{x_lo};{x_hi};{x_hi}"/><animate attributeName="x2" dur="{cycle}s" '
                f'repeatCount="indefinite" keyTimes="0;{f(t_a / cycle)};{f(t_b / cycle)};1" values="{x_lo};{x_lo};{x_hi};{x_hi}"/>'
                f'<animate attributeName="opacity" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;{f((t_a - 0.1) / cycle)};{f(t_a / cycle)};{f(t_b / cycle)};{f((t_b + 0.3) / cycle)};1" '
                'values="0;0;.55;.55;0;0"/></line>')
    body.append(text(w / 2, 572, "L_eff ≈ max(0, L_sys − L_pred) is a conceptual relation only. Effective latency is claimed nowhere until the live measurement (Phase 18) exists.",
                     12, MUTED, "middle"))
    return svg(w, h, "Reactive versus anticipatory commit (concept)",
               "Concept figure, not data: a stick tip falls onto the impact surface. The reactive arm commits after the "
               "crossing has been observed; the anticipatory arms commit earlier from the motion so far; both then pay "
               "the audio latency.", "".join(body), BG_DEFS.format(w=w, h=h) + "".join(clips), STAR_CSS)


def pin(x: float, y: float, col: str, label: str, side: str = "mid") -> str:
    if side == "mid":
        lab = text(x, y + 20, label, 11.5, col, "middle", "b")
    else:
        lab = text(x + (-9 if side == "left" else 9), y + 4, label, 11.5, col, "end" if side == "left" else "start", "b")
    return (f'<line x1="{f(x)}" y1="{f(y - 16)}" x2="{f(x)}" y2="{f(y)}" stroke="{col}" stroke-width="2"/>'
            f'<circle cx="{f(x)}" cy="{f(y)}" r="4.5" fill="{col}"/>{lab}')


def bracket(x0: float, x1: float, y: float, label: str, col: str) -> str:
    return (f'<path d="M{f(x0)} {f(y - 6)}V{f(y)}H{f(x1)}V{f(y - 6)}" fill="none" stroke="{col}" stroke-width="1.8" stroke-linecap="round"/>'
            f'<rect x="{f((x0 + x1) / 2 - 30)}" y="{f(y - 9)}" width="60" height="18" rx="9" fill="#0d1330" stroke="{col}" stroke-width="1.2"/>'
            f'{text((x0 + x1) / 2, y + 4, label, 11.5, col, "middle", "mono b")}')


# ----------------------------------------------------------------------------- concept: strike geometry


def strike_geometry() -> str:
    w, h, cycle = 1160, 540, 11.0
    y_s, x_c = 400.0, 400.0
    k_pts = [(330 + 12 * k, 80.9 + 6.92 * k * k) for k in range(8)]
    u = (y_s - k_pts[6][1]) / (k_pts[7][1] - k_pts[6][1])  # crossing between samples 6 and 7
    cross = (k_pts[6][0] + u * (k_pts[7][0] - k_pts[6][0]), y_s)
    x5, y5 = k_pts[5]
    keep = cycle - 1.6  # everything fades out before the loop restarts
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(34, w, h, 47)}</g>']
    body.append(text(36, 40, "CONCEPT  ·  FROM SAMPLES TO A STRIKE", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    body.append(f'<g>{rect(w - 330, 22, 294, 26, 13, "none", B, 1.4)}{text(w - 183, 40, "ILLUSTRATIVE  ·  NOT MEASURED DATA", 11, B, "middle", "b", LS15)}</g>')
    body.append(rect(24, 64, 700, 452, 18, "#0d1330", LINE, 1.2))
    body.append(text(374, 96, "stick tip, one sample per camera frame", 12, MUTED, "start", "mono"))
    # the pad and its impact surface
    body.append(rect(236, y_s, 328, 66, 14, "#2c3146", "#cfd3df", 2))
    body.append(f'<ellipse cx="{x_c}" cy="{y_s + 33}" rx="118" ry="20" fill="url(#silver)" opacity=".92"/>')
    body.append(f'<line x1="256" y1="{y_s}" x2="544" y2="{y_s}" stroke="{A}" stroke-width="5" stroke-linecap="round" filter="url(#glow)"/>')
    body.append(text(574, y_s + 4, "impact surface", 12, A, "start", "mono"))
    body.append(f'<path d="M256 {y_s + 6}v30m-5 -8 5 8 5 -8" fill="none" stroke="{A}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
                f'{text(244, y_s + 26, "inward normal", 11, A, "end", "mono")}')
    # observed samples t0..t7, one per frame
    for k, (x, y) in enumerate(k_pts):
        t = 0.7 + 0.45 * k if k < 6 else (5.0 if k == 6 else 5.5)
        label = text(x - 10, y + 4, f"t{k}", 10.5, MUTED, "end", "mono") if k >= 3 else ""
        body.append(f'<g><circle cx="{f(x)}" cy="{f(y)}" r="5" fill="{A}" stroke="#fff" stroke-width="1.6"/>{label}{appear(t, cycle, keep, 0.25)}</g>')
        if k > 0:
            x0, y0 = k_pts[k - 1]
            body.append(f'<line x1="{f(x0)}" y1="{f(y0)}" x2="{f(x)}" y2="{f(y)}" stroke="{A}" stroke-width="1.6" opacity=".55">{appear(t, cycle, keep, 0.25, 0.55)}</line>')
    # prediction made at sample 5: constant-acceleration extrapolation (arm B)
    pred = [(330 + 12 * (5 + (cross[0] - x5) / 12 * i / 20), 80.9 + 6.92 * (5 + (cross[0] - x5) / 12 * i / 20) ** 2) for i in range(21)]
    dd = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in pred)
    body.append(f'<path d="{dd}" fill="none" stroke="{B}" stroke-width="3" stroke-dasharray="3 6" stroke-linecap="round" opacity=".95">{appear(3.9, cycle, keep, 0.4, 0.95)}</path>')
    mid = ((x5 + cross[0]) / 2 + 30, (y5 + y_s) / 2)
    body.append(f'<g><circle cx="{f(cross[0])}" cy="{f(y_s)}" r="7" fill="{B}" opacity=".9"/>'
                f'<path d="M{f(x5 + 22)} {f(y5)}h12L{f(cross[0] + 34)} {f(y_s)}h-12" fill="none" stroke="{B}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<rect x="{f(mid[0] - 18)}" y="{f(mid[1] - 9)}" width="36" height="18" rx="9" fill="#0d1330" stroke="{B}" stroke-width="1.2"/>'
                f'{text(mid[0], mid[1] + 4, "TTI", 11.5, B, "middle", "mono b")}'
                f'{text(cross[0] + 62, y_s - 62, "predicted crossing", 12, B, "start", "b")}'
                f'{text(cross[0] + 62, y_s - 46, "rule-based candidate (arm B)", 11, B, "start")}'
                f'<path d="M{f(cross[0] + 10)} {f(y_s - 8)}L{f(cross[0] + 56)} {f(y_s - 52)}" stroke="{B}" stroke-width="1.4" fill="none"/>{appear(4.4, cycle, keep, 0.3)}</g>')
    # the crossing, interpolated between samples 6 and 7
    body.append(f'<g><circle cx="{f(cross[0])}" cy="{f(y_s)}" r="9" fill="none" stroke="#fff" stroke-width="2.4"/>'
                f'{text(cross[0] - 18, y_s - 52, "t* = t6 + u · Δt", 13, "#ffffff", "end", "mono b")}'
                f'{text(cross[0] - 18, y_s - 34, "interpolated crossing", 11, MUTED, "end")}{appear(5.6, cycle, keep, 0.3)}</g>')
    body.append(f'<circle cx="{f(cross[0])}" cy="{f(y_s)}" r="6" fill="none" stroke="#fff" stroke-width="2.5" opacity="0">{pulse(5.6, cycle, 0.9, {"r": (6, 46)}, 0.9)}</circle>')
    body.append(f'<g><path d="M{f(k_pts[7][0] + 8)} {f(k_pts[7][1] + 2)}L576 {f(y_s + 40)}" stroke="{A}" stroke-width="1.4" fill="none"/>'
                f'{text(582, y_s + 38, "first frame after the crossing", 11, A, "start")}'
                f'{text(582, y_s + 54, "(arm A reacts here)", 11, A, "start", "b")}{appear(5.5, cycle, keep, 0.3)}</g>')
    body.append(f'<g><circle cx="{f(x_c + 150)}" cy="{f(y_s - 120)}" r="22" fill="{OK}" fill-opacity=".15" stroke="{OK}" stroke-width="2.4"/>'
                f'<path d="M{f(x_c + 140)} {f(y_s - 120)}l7 8 13 -16" fill="none" stroke="{OK}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>'
                f'{text(x_c + 150, y_s - 84, "COMMIT", 12.5, OK, "middle", "bb", LS15)}{appear(6.6, cycle, keep, 0.3)}</g>')
    # rules panel, each card lights up when its rule is at work
    rules = [("Downward entry only", "Crossing the impact surface along its inward normal counts. Upward crossings never do.", 5.6),
             ("One commit per entry episode", "The first valid entry commits; the tip must leave the zone before it can strike again.", 6.6),
             ("Refractory timers", "A short per-hand and per-zone dead time suppresses duplicates and jitter re-entries.", 7.1),
             ("Sub-frame crossing time", "Linear interpolation between the two surrounding samples, not the nearest frame (ADR-0020).", 5.6)]
    for i, (head, tail, t_hi) in enumerate(rules):
        y = 64 + i * 114
        body.append(rect(748, y, 388, 102, 16, "#0d1330", LINE, 1.2))
        body.append(f'<rect x="747" y="{y - 1}" width="390" height="104" rx="17" fill="none" stroke="{OK}" stroke-width="2.4" opacity="0">{appear(t_hi, cycle, t_hi + 1.6, 0.3, 0.95)}</rect>')
        body.append(f'<circle cx="780" cy="{y + 30}" r="13" fill="{A}" fill-opacity=".14" stroke="{A}" stroke-width="1.5"/>{text(780, y + 35, str(i + 1), 13, A, "middle", "b")}')
        body.append(text(804, y + 35, head, 15, INK, "start", "b"))
        for j, ln in enumerate(wrap(tail, 48)[:3]):
            body.append(text(768, y + 62 + j * 16, ln, 12.5, MUTED))
    defs = (BG_DEFS.format(w=w, h=h) +
            '<radialGradient id="silver" cx=".5" cy=".4" r=".75"><stop offset="0" stop-color="#fbfcff"/><stop offset=".55" stop-color="#b9c0cd"/><stop offset="1" stop-color="#6b7388"/></radialGradient>'
            '<filter id="glow" x="-10%" y="-200%" width="120%" height="500%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    return svg(w, h, "From samples to a strike (concept)",
               "Concept figure, not data: tip samples fall toward an impact surface; a rule-based candidate predicts the "
               "crossing, the crossing time is interpolated between two samples, and one commit is made per entry.",
               "".join(body), defs, STAR_CSS)


# ----------------------------------------------------------------------------- the kit


def waveform(wav: Path, w: float = 190.0, h: float = 34.0, bins: int = 76) -> tuple[str, float]:
    import soundfile as sf

    data, rate = sf.read(str(wav), always_2d=True)
    mono = np.abs(data.mean(axis=1))
    edges = np.linspace(0, len(mono), bins + 1).astype(int)
    amp = np.array([mono[a:b].max() if b > a else 0.0 for a, b in zip(edges, edges[1:], strict=False)])
    amp = amp / max(float(amp.max()), 1e-9)
    mid = h / 2
    top = [(i * w / bins, mid - max(1.0, a * mid)) for i, a in enumerate(amp)]
    bot = [(x, 2 * mid - y) for x, y in reversed(top)]
    d = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in [*top, *bot]) + "Z"
    return d, len(mono) / rate


def kit_layout() -> str:
    w, h, cycle = 940, 596, 9.6
    pads = [("CRASH / RIDE", "crash_ride", "tr505-crash", "brass", B, (96, 124)),
            ("HI-HAT", "hihat", "tr505-hihat-closed", "brass", A, (644, 124)),
            ("SNARE", "snare", "tr505-snare", "silver", C, (96, 332)),
            ("TOM 1", "tom1", "tr505-tom-h", "silver", OK, (644, 332))]
    samples = ROOT / "assets" / "samples" / "recorded"
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(40, w, h, 61)}</g>']
    body.append(text(36, 40, "THE KIT  ·  FOUR PADS  ·  MIRRORED DISPLAY", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    # figure and guide brackets
    cx = w / 2
    body.append(f'<g fill="url(#body)" stroke="#9aa6d6" stroke-opacity=".35"><circle cx="{cx}" cy="150" r="36"/>'
                f'<path d="M{cx - 92} 232Q{cx - 92} 196 {cx - 52} 192H{cx + 52}Q{cx + 92} 196 {cx + 92} 232L{cx + 78} 420H{cx - 78}Z"/>'
                f'<rect x="{cx - 14}" y="180" width="28" height="22"/></g>')
    for sx, sy, dx, dy in ((cx - 110, 176, 1, 1), (cx + 110, 176, -1, 1), (cx - 110, 438, 1, -1), (cx + 110, 438, -1, -1)):
        body.append(f'<path d="M{sx + 34 * dx} {sy}H{sx}V{sy + 34 * dy}" fill="none" stroke="#84dcef" stroke-width="3" stroke-linecap="round"/>')
    body.append(text(cx, 462, "stand here", 12, "#84dcef", "middle", "mono", 'opacity=".9"'))
    t_hits = [0.6, 1.8, 3.0, 4.2, 6.0, 7.2]
    order = [0, 1, 2, 3, 0, 3]  # the pad struck at each time, in display order
    for slot, (name, _zid, sample, metal, col, (px, py)) in enumerate(pads):
        body.append(f'<g transform="translate({px} {py})">')
        body.append(rect(0, 0, 200, 88, 14, "#2c3146", "#cfd3df", 2))
        body.append(rect(4, 4, 192, 80, 11, "#3b4158"))
        body.append(f'<ellipse cx="100" cy="44" rx="78" ry="30" fill="url(#{metal})" stroke="#e9e3d2" stroke-opacity=".7"/>')
        if metal == "brass":
            body.append('<ellipse cx="100" cy="44" rx="18" ry="8" fill="#c9a24c" stroke="#8a6420"/><circle cx="100" cy="44" r="3" fill="#3a2d12"/>')
        body.append('<line x1="16" y1="12" x2="184" y2="12" stroke="#ffe27a" stroke-width="3" stroke-linecap="round" opacity=".9"/>')
        times = [t for t, s in zip(t_hits, order, strict=False) if s == slot]
        for t in times:
            body.append(f'<ellipse cx="100" cy="44" rx="78" ry="30" fill="{col}" opacity="0">{pulse(t, cycle, 0.5, {}, 0.5)}</ellipse>')
            body.append(f'<ellipse cx="100" cy="12" rx="8" ry="3" fill="none" stroke="{col}" stroke-width="3" opacity="0">{pulse(t, cycle, 1.0, {"rx": (8, 130), "ry": (3, 46)}, 0.85)}</ellipse>')
        body.append(text(100, 112, name, 13, INK, "middle", "bb", 'letter-spacing="2"'))
        body.append(text(100, 130, sample, 11.5, col, "middle", "mono b"))
        try:
            d, dur = waveform(samples / f"{sample}.wav")
            body.append(f'<g transform="translate(5 142)">{rect(-5, -4, 200, 42, 10, "#0b1128", LINE, 1)}'
                        f'<path d="{d}" fill="{col}" fill-opacity=".35" stroke="{col}" stroke-width="1" transform="translate(5 2)"/>')
            for t in times:
                body.append(f'<line x1="5" y1="-2" x2="5" y2="38" stroke="#fff" stroke-width="1.8" opacity="0">'
                            f'<animate attributeName="x1" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;{f(t / cycle)};{f(min(t + dur, cycle - 0.1) / cycle)};1" values="5;5;195;195"/>'
                            f'<animate attributeName="x2" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;{f(t / cycle)};{f(min(t + dur, cycle - 0.1) / cycle)};1" values="5;5;195;195"/>'
                            f'<animate attributeName="opacity" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;{f(max(t - 0.001, 0) / cycle)};{f(t / cycle)};{f(min(t + dur, cycle - 0.1) / cycle)};1" values="0;0;.9;.9;0"/></line>')
            body.append(f'{text(192, 52, f"{dur:.2f} s", 10, MUTED, "end", "mono")}</g>')
        except (OSError, RuntimeError, ImportError) as exc:  # the samples are fetched, not tracked
            raise SystemExit(f"{sample}.wav is missing or unreadable ({exc}); run scripts/fetch_drum_samples.py first") from exc
        body.append("</g>")
    body.append(text(cx, 566, "Camera coordinates never change; only the picture on screen is mirrored. Samples are recorded, never synthesised at run time.", 12, MUTED, "middle"))
    defs = (BG_DEFS.format(w=w, h=h) +
            '<linearGradient id="body" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4a5681"/><stop offset="1" stop-color="#262d4a"/></linearGradient>'
            '<radialGradient id="brass" cx=".5" cy=".4" r=".75"><stop offset="0" stop-color="#f6e3a1"/><stop offset=".5" stop-color="#d4a94a"/><stop offset="1" stop-color="#7d5a1f"/></radialGradient>'
            '<radialGradient id="silver" cx=".5" cy=".4" r=".75"><stop offset="0" stop-color="#fbfcff"/><stop offset=".55" stop-color="#b9c0cd"/><stop offset="1" stop-color="#6b7388"/></radialGradient>')
    return svg(w, h, "The four-pad kit", "Animated layout of the four pads in display order with the waveform of each "
               "recorded sample; pads pulse as they are struck.", "".join(body), defs, STAR_CSS)


# ----------------------------------------------------------------------------- roadmap


def roadmap() -> str:
    w, h, cycle = 1240, 520, 18.0
    names = ["Definition", "Architecture", "Capture", "Hands +|stick", "Geometry +|audio", "Rule|baselines", "Data|collection",
             "Dataset +|labels", "Features", "GBDT +|evaluation", "Temporal|AI", "Multi-task", "Extensions", "Realtime|inference",
             "Calibration", "Debug|dashboard", "Performance", "Hardening", "Evaluation", "Ablations", "Final|integration",
             "Thesis|material", "Graduation|demo", "Packaging"]
    groups = [("foundations", A, range(0, 3)), ("perception to baselines", "#9b8cff", range(3, 10)),
              ("learning", B, range(10, 14)), ("product", OK, range(14, 18)), ("evaluation", C, range(18, 20))]

    def colour(i: int) -> str:
        return next((c for _, c, r in groups if i in r), DIM)

    def x_of(i: int) -> float:
        return 74 + (i % 12) * 98

    def y_of(i: int) -> float:
        return 128 if i < 12 else 322

    x11, x12, y0, y1 = x_of(11), x_of(12), y_of(0), y_of(12)
    y_mid = (y0 + y1) / 2 + 6
    ret = (f"H{x11 + 34}Q{x11 + 62} {y0} {x11 + 62} {y0 + 28}V{y_mid - 28}Q{x11 + 62} {y_mid} {x11 + 34} {y_mid}"
           f"H{x12 - 34}Q{x12 - 62} {y_mid} {x12 - 62} {y_mid + 28}V{y1 - 28}Q{x12 - 62} {y1} {x12 - 34} {y1}H{x12}")
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(36, w, h, 71)}</g>']
    body.append(text(36, 40, "ROADMAP  ·  24 PHASES  ·  EACH ENDS AT AN OWNER-SIGNED EXIT GATE", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    rails = f"M{x_of(0)} {y0}H{x11}{ret}H{x_of(23)}"
    body.append(f'<path d="{rails}" stroke="{LINE}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    run = f"M{x_of(0)} {y0}H{x11}{ret}H{x_of(19)}"
    for i, nm in enumerate(names):
        x, y = x_of(i), y_of(i)
        built, pending, col = i <= 19, 3 <= i <= 19, colour(i)
        if built:
            body.append(f'<circle cx="{x}" cy="{y}" r="22" fill="{col}" fill-opacity=".16" stroke="{col}" stroke-width="2.4"/>')
            if pending:
                body.append(f'<circle cx="{x}" cy="{y}" r="29" fill="none" stroke="{col}" stroke-width="1.6" stroke-dasharray="3 5" opacity=".85">'
                            f'<animateTransform attributeName="transform" type="rotate" from="0 {x} {y}" to="360 {x} {y}" dur="14s" repeatCount="indefinite"/></circle>')
        else:
            body.append(f'<circle cx="{x}" cy="{y}" r="22" fill="none" stroke="{DIM}" stroke-width="2" stroke-dasharray="4 5">'
                        f'<animate attributeName="opacity" values=".45;.9;.45" dur="3.6s" begin="{f((i - 20) * 0.5)}s" repeatCount="indefinite"/></circle>')
        body.append(text(x, y + 5.5, f"{i:02d}", 15, INK if built else MUTED, "middle", "bb"))
        for j, ln in enumerate(nm.split("|")):
            body.append(text(x, y + 46 + j * 14, ln, 11.5, INK if built else DIM, "middle", "b" if built else ""))
    body.append(f'<circle r="7" fill="#fff" filter="url(#dot)" opacity="1"><animateMotion dur="{cycle}s" repeatCount="indefinite" path="{run}" keyPoints="0;1;1" keyTimes="0;.7;1" calcMode="linear"/>'
                f'<animate attributeName="opacity" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;.68;.72;1" values="1;1;0;0"/></circle>')
    ax, ay = x_of(19), y_of(19)
    body.append(f'<g>{rect(ax - 214, ay + 84, 262, 46, 12, "#0d1330", OK, 1.4)}{text(ax - 83, ay + 104, "latest: standing four-pad product", 12, OK, "middle", "b")}'
                f'{text(ax - 83, ay + 120, "candidate (ADR-0045), live acceptance pending", 10.5, MUTED, "middle")}'
                f'<path d="M{ax + 4} {ay + 84}Q{ax + 4} {ay + 56} {ax} {ay + 36}" fill="none" stroke="{OK}" stroke-width="1.6" stroke-dasharray="3 4"/></g>')
    # legends
    body.append(f'<circle cx="44" cy="466" r="8" fill="{MUTED}" fill-opacity=".16" stroke="{MUTED}" stroke-width="2"/>{text(62, 471, "built", 12, MUTED)}')
    body.append(f'<circle cx="124" cy="466" r="7" fill="{MUTED}" fill-opacity=".16" stroke="{MUTED}" stroke-width="2"/><circle cx="124" cy="466" r="11" fill="none" stroke="{MUTED}" stroke-dasharray="2 3"/>'
                f'{text(144, 471, "built, evidence still pending (participants, live runs, sign-off)", 12, MUTED)}')
    body.append(f'<circle cx="540" cy="466" r="8" fill="none" stroke="{DIM}" stroke-width="2" stroke-dasharray="3 3"/>{text(558, 471, "planned", 12, MUTED)}')
    lx = 36
    for label, col, _ in groups:
        body.append(f'<rect x="{lx}" y="490" width="12" height="12" rx="3" fill="{col}"/>{text(lx + 18, 500.5, label, 11.5, MUTED)}')
        lx += 18 + len(label) * 6.4 + 26
    return svg(w, h, "Space Drums roadmap",
               "Twenty-four phases from project definition to final packaging. Phases 00 to 19 have their machinery built; "
               "phases 20 to 23 are planned; evidence from participants and live runs is still pending for most.",
               "".join(body), BG_DEFS.format(w=w, h=h) +
               '<filter id="dot" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
               STAR_CSS)


# ----------------------------------------------------------------------------- architecture layers


def architecture() -> str:
    w, h, cycle = 1160, 676, 12.0
    layers = [
        ("L9", "ablation", "feature, history and horizon ablations", C),
        ("L8", "app  ·  live_eval", "composition root: live loop, record and replay, calibrate, play  ·  confirmatory analysis", C),
        ("L7", "ui  ·  eval  ·  data  ·  calib", "overlay and dashboard  ·  evaluation harness  ·  recording  ·  calibration wizard", "#9b8cff"),
        ("L6", "commit  ·  audio", "commit policy and refractory timers  ·  sample bank, scheduler, mixer", OK),
        ("L5", "prediction  ·  models", "rule-based extrapolation  ·  GBDT, GRU, TCN, multi-task", B),
        ("L4", "features  ·  geometry", "causal kinematics  ·  zones, impact surfaces, crossings", "#4ee0c1"),
        ("L3", "tracking", "per-hand causal filter and state machine", "#9b8cff"),
        ("L2", "stick  ·  hands", "stick endpoint estimation  ·  MediaPipe hand landmarks", A),
        ("L1", "capture", "timestamped frames, fixed ROI, bounded queue", A),
        ("L0", "contracts  ·  timing  ·  config", "records  ·  the one monotonic clock  ·  schema-validated configuration", INK),
    ]
    x0, bw, bh, gap, y0 = 82, 680, 46, 10, 86
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(36, w, h, 97)}</g>']
    body.append(text(36, 40, "ARCHITECTURE  ·  A LAYER MAY IMPORT ONLY FROM THE LAYERS BELOW IT", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    # the downward "may import" rail
    rail_x = 48
    y_bot = y0 + len(layers) * (bh + gap) - gap
    body.append(f'<line x1="{rail_x}" y1="{y0 - 6}" x2="{rail_x}" y2="{y_bot + 4}" stroke="{LINE}" stroke-width="3" stroke-dasharray="2 8" stroke-linecap="round"/>')
    body.append(f'<path d="M{rail_x - 7} {y_bot - 6}L{rail_x} {y_bot + 6}L{rail_x + 7} {y_bot - 6}" fill="none" stroke="{DIM}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')
    for i, (tag, name, desc, col) in enumerate(layers):
        y = y0 + i * (bh + gap)
        t = 0.5 + i * (cycle - 3.0) / len(layers)
        body.append(rect(x0, y, bw, bh, 12, "#0f1630", LINE, 1.5))
        body.append(f'<rect x="{x0 - 2}" y="{y - 2}" width="{bw + 4}" height="{bh + 4}" rx="14" fill="none" stroke="{col}" stroke-width="2.4" opacity="0">{pulse(t, cycle, 0.9, {}, 0.95)}</rect>')
        body.append(rect(x0 + 1, y + 1, 5, bh - 2, 2.5, col))
        body.append(text(x0 + 24, y + 29, tag, 13, col, "start", "mono b"))
        body.append(text(x0 + 62, y + 20, name, 14.5, INK, "start", "bb", 'letter-spacing=".4"'))
        body.append(text(x0 + 62, y + 36, desc, 11.5, MUTED))
    # a packet that walks down the rail, lighting each layer
    kt = ";".join(f(k) for k in [0, 0.5 / cycle, (cycle - 2.5) / cycle, 1])
    body.append(f'<circle r="6" fill="#fff" cx="{rail_x}" filter="url(#dot)"><animate attributeName="cy" dur="{cycle}s" repeatCount="indefinite" keyTimes="{kt}" values="{f(y0 + bh / 2)};{f(y0 + bh / 2)};{f(y_bot - bh / 2)};{f(y_bot - bh / 2)}"/>'
                f'<animate attributeName="opacity" dur="{cycle}s" repeatCount="indefinite" keyTimes="0;.04;.84;.9;1" values="0;1;1;0;0"/></circle>')
    # forbidden imports
    px = 800
    body.append(text(px, 70, "FORBIDDEN BY CONTRACT", 12, "#ff7b8a", "start", "b", 'letter-spacing="3"'))
    rules = [
        ("prediction", "geometry", "A predictor cannot peek at the zones.", 1.4),
        ("commit", "perception", "Commit sees only StrikeCandidate and TrackState: never perception, prediction or features.", 3.6),
        ("causal stages", "offline labels", "No future information can reach the live path.", 5.8),
        ("any layer", "a layer above", "Upward imports break the layers contract.", 8.0),
    ]
    for i, (src, dst, note, t) in enumerate(rules):
        y = 86 + i * 138
        body.append(rect(px, y, 330, 122, 16, "#0d1330", LINE, 1.2))
        body.append(rect(px + 16, y + 18, 112, 30, 15, "none", MUTED, 1.4))
        body.append(text(px + 72, y + 38, src, 12.5, INK, "middle", "mono b"))
        body.append(rect(px + 202, y + 18, 112, 30, 15, "none", MUTED, 1.4))
        body.append(text(px + 258, y + 38, dst, 12.5, INK, "middle", "mono b"))
        body.append(f'<path d="M{px + 134} {y + 33}H{px + 196}" stroke="#ff7b8a" stroke-width="2.4" stroke-dasharray="5 5" stroke-linecap="round"/>')
        body.append(f'<path d="M{px + 196} {y + 33}l-8 -6m8 6l-8 6" stroke="#ff7b8a" stroke-width="2.4" stroke-linecap="round" fill="none"/>')
        body.append(f'<g transform="translate({px + 165} {y + 33})" opacity="0"><circle r="12" fill="#1a0e1c" stroke="#ff4d6d" stroke-width="2.4"/>'
                    f'<path d="M-5 -5L5 5M5 -5L-5 5" stroke="#ff4d6d" stroke-width="2.6" stroke-linecap="round"/>{appear(t, cycle, cycle - 0.4, 0.25)}</g>')
        for j, ln in enumerate(wrap(note, 44)[:3]):
            body.append(text(px + 18, y + 78 + j * 16, ln, 12, MUTED))
    body.append(text(w / 2, 660, "Seven import contracts (the layer order plus the rules above) are checked by lint-imports and by tests/architecture.", 12, MUTED, "middle"))
    return svg(w, h, "Space Drums layered architecture",
               "Ten layers from contracts at the bottom to ablation at the top; a layer may import only from the layers below it. "
               "Four import rules are forbidden by contract: prediction to geometry, commit to perception, causal stages to offline labels, "
               "and upward imports.", "".join(body), BG_DEFS.format(w=w, h=h) +
               '<filter id="dot" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>', STAR_CSS)


# ----------------------------------------------------------------------------- per-hand tracking states


def qpoint(p0, c, p1, t):
    return ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1])


def tracking_states() -> str:
    w, h, cycle = 1160, 580, 15.0
    nw, nh = 200, 90
    centre = {"VALID": (200.0, 160.0), "DEGRADED": (580.0, 160.0), "STALE": (960.0, 160.0), "INVALID": (580.0, 400.0)}
    colors = {"VALID": OK, "DEGRADED": B, "INVALID": "#ff5d73", "STALE": "#8f98b5"}
    commits = {"VALID": "commits allowed", "DEGRADED": "commits off by default", "INVALID": "never commits", "STALE": "never commits"}
    gap_label = "gap > g_max or confidence < c_min"
    # name: (start, control, end, label lines, label x, label y, anchor)
    arcs = {
        "v_d": ((300, 142), (390, 142), (480, 142), ("low confidence, or a", "short gap bridged"), 390, 100, "middle"),
        "d_v": ((480, 180), (390, 180), (300, 180), ("confident observation again",), 390, 206, "middle"),
        "d_s": ((680, 142), (770, 142), (860, 142), ("last valid observation", "older than age_max"), 770, 100, "middle"),
        "v_s": ((236, 115), (580, 14), (924, 115), ("the same time-out applies from VALID",), 580, 52, "middle"),
        "d_i": ((580, 205), (580, 275), (580, 355), (gap_label,), 600, 282, "start"),
        "v_i": ((250, 205), (290, 360), (480, 384), (gap_label,), 352, 300, "start"),
        "i_v": ((480, 420), (190, 430), (176, 205), ("fresh observation,", "confidence >= c_valid"), 214, 452, "start"),
        "s_i": ((960, 205), (940, 372), (680, 392), ("treated as INVALID,", "must re-acquire"), 910, 330, "start"),
    }
    path_of = {k: f"M{f(a_[0][0])} {f(a_[0][1])}Q{f(a_[1][0])} {f(a_[1][1])} {f(a_[2][0])} {f(a_[2][1])}" for k, a_ in arcs.items()}
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(34, w, h, 53)}</g>']
    body.append(text(36, 40, "EACH HAND  ·  ITS OWN TRACKING STATE", 12, MUTED, "start", "b", 'letter-spacing="3"'))
    for k, (_p0, c, p1, lines, lx, ly, anchor) in arcs.items():
        body.append(f'<path d="{path_of[k]}" fill="none" stroke="#33407a" stroke-width="2.6" stroke-linecap="round"/>')
        ang = math.atan2(p1[1] - c[1], p1[0] - c[0])
        body.append(f'<path d="M{f(p1[0])} {f(p1[1])}l{f(-12 * math.cos(ang - .45))} {f(-12 * math.sin(ang - .45))}M{f(p1[0])} {f(p1[1])}l{f(-12 * math.cos(ang + .45))} {f(-12 * math.sin(ang + .45))}" stroke="#5a6aa8" stroke-width="2.6" stroke-linecap="round" fill="none"/>')
        for j, ln in enumerate(lines):
            body.append(text(lx, ly + j * 15, ln, 11.5, MUTED, anchor))
    for name, (cx, cy) in centre.items():
        col = colors[name]
        body.append(rect(cx - nw / 2, cy - nh / 2, nw, nh, 18, "#0f1630", col, 2.2))
        body.append(text(cx, cy - 4, name, 21, col, "middle", "bb", 'letter-spacing="2"'))
        body.append(text(cx, cy + 22, commits[name], 12.5, MUTED, "middle"))
    body.append(text(centre["INVALID"][0], centre["INVALID"][1] + nh / 2 + 24, "predictor and feature history are reset", 11.5, "#ff9aa8", "middle", "", ITALIC))
    # a typical story: (state or edge, from, to)
    story = [("VALID", 0.0, 1.0), ("v_d", 1.0, 1.9), ("DEGRADED", 1.9, 2.9), ("d_v", 2.9, 3.8), ("VALID", 3.8, 4.8),
             ("v_i", 4.8, 5.9), ("INVALID", 5.9, 7.1), ("i_v", 7.1, 8.3), ("VALID", 8.3, 9.0), ("v_d", 9.0, 9.8),
             ("DEGRADED", 9.8, 10.4), ("d_s", 10.4, 11.5), ("STALE", 11.5, 12.3), ("s_i", 12.3, 13.1), ("INVALID", 13.1, 13.6),
             ("i_v", 13.6, 14.8)]
    for key, t0, t1 in story:
        if key in centre:
            cx, cy = centre[key]
            body.append(f'<rect x="{cx - nw / 2 - 3}" y="{cy - nh / 2 - 3}" width="{nw + 6}" height="{nh + 6}" rx="21" fill="{colors[key]}" fill-opacity=".14" stroke="{colors[key]}" stroke-width="3" opacity="0">{appear(t0, cycle, t1, 0.2, 0.95)}</rect>')
        else:
            body.append(f'<path d="{path_of[key]}" fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round" opacity="0">{appear(t0, cycle, t1, 0.15, 0.9)}</path>')
    pts = []
    for key, t0, t1 in story:
        if key in centre:
            cx, cy = centre[key]
            q = (cx, cy - nh / 2 - 18) if key != "INVALID" else (cx - 84, cy - nh / 2 - 18)
            pts += [(t0, q[0], q[1], "io"), (t1, q[0], q[1], "io")]
        else:
            p0, c, p1 = arcs[key][:3]
            for i in range(13):
                q = qpoint(p0, c, p1, i / 12)
                pts.append((t0 + (t1 - t0) * i / 12, q[0], q[1], "io"))
    cleaned = [pts[0]]
    for t, x, y, e in pts[1:]:
        cleaned.append((max(t, cleaned[-1][0] + 0.001), x, y, e))
    cleaned.append((cycle, cleaned[0][1], cleaned[0][2], "io"))
    body.append(f'<circle r="8" fill="#fff" filter="url(#dot)">{keyed_translate(cleaned, cycle)}</circle>')
    body.append(text(w / 2, 548, "Losing the hand resets the predictor instead of inventing a strike. A commit needs a fresh, confident observation unless DEGRADED commits are explicitly enabled (ADR-0039).", 12, MUTED, "middle"))
    return svg(w, h, "Per-hand tracking states",
               "State machine of one hand: VALID, DEGRADED, INVALID and STALE, with the transitions between them. A light token walks "
               "through a typical sequence; only VALID commits by default and INVALID or STALE reset the predictor.",
               "".join(body), BG_DEFS.format(w=w, h=h) +
               '<filter id="dot" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>', STAR_CSS)


# ----------------------------------------------------------------------------- footer


def footer() -> str:
    w, h = 1240, 170
    wave = lambda amp, per, y: ("M0 " + str(y) + " " + "".join(f"q{per / 4} {-amp} {per / 2} 0 t{per / 2} 0 " for _ in range(int(w / per * 2) + 4)))  # noqa: E731
    body = [rect(0, 0, w, h, 24, "url(#bg)"), f'<g clip-path="url(#round)">{stars(40, w, h, 83, ymax=110)}']
    for amp, per, y, col, op, dur in ((16, 220, 132, A, 0.22, 9), (12, 160, 142, "#9b8cff", 0.25, 6.5), (9, 120, 150, C, 0.25, 4.5)):
        body.append(f'<path d="{wave(amp, per, y)} V{h} H0Z" fill="{col}" opacity="{op}"><animateTransform attributeName="transform" type="translate" from="0 0" to="-{per} 0" dur="{dur}s" repeatCount="indefinite"/></path>')
    body.append("</g>")
    body.append(f'<text x="{w / 2}" y="62" font-size="30" class="bb" text-anchor="middle" fill="url(#ft)" letter-spacing="6">SPACE DRUMS</text>')
    body.append(text(w / 2, 90, "A graduation project  ·  Python  ·  OpenCV  ·  MediaPipe  ·  PyTorch", 13.5, MUTED, "middle"))
    body.append(text(w / 2, 112, "Measure everything. Fabricate nothing.", 13, INK, "middle", "b", 'letter-spacing="2"'))
    defs = (BG_DEFS.format(w=w, h=h) +
            f'<linearGradient id="ft" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{w}" y2="0"><stop offset="0" stop-color="{A}"/><stop offset=".5" stop-color="#9b8cff"/><stop offset="1" stop-color="{C}"/></linearGradient>')
    return svg(w, h, "Space Drums footer", "Animated waves under the project name.", "".join(body), defs, STAR_CSS)


# ----------------------------------------------------------------------------- driver

ASSETS = {
    "hero": ("hero.svg", hero),
    "typing": ("typing.svg", typing),
    "divider": ("divider.svg", divider),
    "pipeline": ("pipeline.svg", pipeline),
    "anticipation": ("concept-anticipation.svg", concept_anticipation),
    "geometry": ("concept-strike-geometry.svg", strike_geometry),
    "kit": ("kit-layout.svg", kit_layout),
    "roadmap": ("roadmap.svg", roadmap),
    "architecture": ("architecture-layers.svg", architecture),
    "states": ("tracking-states.svg", tracking_states),
    "footer": ("footer.svg", footer),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=sorted(ASSETS), default=None)
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (name, fn) in ASSETS.items():
        if args.only in (None, key):
            path = OUT / name
            path.write_text(fn(), encoding="utf-8", newline="\n")
            print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1e3:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
