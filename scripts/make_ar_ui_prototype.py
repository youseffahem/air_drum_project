# ruff: noqa: E501  (SVG / HTML markup literals)
"""Write the interactive prototype of the AR-view concept: one self-contained HTML file.

    python scripts/make_ar_ui_prototype.py                # docs/ui-prototype/ar-view.html

Open the file in a browser (no server, no network). Click a drum, press 1 to 4, or press Space for a
groove: every strike plays the project's recorded TR-505 sample for that drum (public domain, see
``assets/samples/LICENSES.md``) and fires the ring, flash and spark effects of the README animation.
The sensitivity and volume sliders can be dragged, the camera menu and the settings panel open.

**This is a design prototype, not the application.** It uses no camera, no hand tracking and no
decision pipeline; the photo is the owner's concept render, the HUD values are placeholders, and the
page says so in its own corner. It reuses the vector UI of ``make_ar_ui_concept.py`` (same file, same
geometry) so the README animation and the prototype cannot drift apart.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_ar_ui_concept as ar  # noqa: E402
import make_readme_svgs as ms  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "ui-prototype" / "ar-view.html"
SAMPLE_DIR = ROOT / "assets" / "samples" / "recorded"
SAMPLE_FILES = {"crash": "tr505-crash.wav", "tom": "tr505-tom-h.wav", "snare": "tr505-snare.wav", "hihat": "tr505-hihat-closed.wav"}
HAND = {"crash": "L", "tom": "L", "snare": "R", "hihat": "R"}
KEYS = {"1": "crash", "2": "tom", "3": "snare", "4": "hihat"}
CAMERAS = ["Front (Default)", "Back camera", "External USB camera", "Virtual camera (OBS)"]
GROOVE_ID = 'id="grooveText"'
SWITCHES = [("Hand brackets", "brackets"), ("Stick trails", "trails"), ("Scan sweep", "scan"), ("Drifting dust", "dust"), ("Strike sparks", "sparks"), ("Ambient motion", "motion")]


def samples() -> dict[str, str]:
    out = {}
    for pad, name in SAMPLE_FILES.items():
        path = SAMPLE_DIR / name
        if not path.exists():
            raise SystemExit(f"{path} is missing; run scripts/fetch_drum_samples.py first")
        out[pad] = "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return out


def button(gid: str, label: str, body: str) -> str:
    return f'<g id="{gid}" role="button" tabindex="0" aria-label="{label}">{body}</g>'


def pads_layer() -> str:
    out = []
    for key, p in ar.PADS.items():
        cx, cy = p["c"]
        out.append(f'<g class="padfx" data-pad="{key}" transform="translate({cx} {cy}) rotate({p["rot"]})">'
                   f'<ellipse class="padhit" data-pad="{key}" rx="{p["rx"]}" ry="{p["ry"]}"/></g>')
    return "".join(out)


def menu_layer() -> str:
    x, y, w = 231, 684, 242
    h = 12 + 38 * len(CAMERAS)
    rows = []
    for i, name in enumerate(CAMERAS):
        ry = y + 6 + 38 * i
        rows.append(f'<g class="mi" role="option" tabindex="0" data-i="{i}" aria-label="{name}">'
                    f'<rect class="mibg hit" x="{x + 6}" y="{ry}" width="{w - 12}" height="36" rx="8" fill="#fff" fill-opacity="0" pointer-events="all"/>'
                    f'{ms.text(x + 20, ry + 24, name, 18, ar.WHITE, "start", "", "")}'
                    f'<path class="tick" d="M{x + w - 34} {ry + 18}l6 6 11 -13" fill="none" stroke="{ar.BLUE}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity="0"/></g>')
    return f'<g id="gMenu" style="display:none">{ar.glass("gMenuBg", x, y, w, h, 12, 0.7)}{"".join(rows)}</g>'


def settings_layer() -> str:
    x, y, w, h = 18, 590, 312, 250
    rows = []
    for i, (label, key) in enumerate(SWITCHES):
        ry = y + 58 + 32 * i
        rows.append(f'<g class="sw" role="switch" tabindex="0" data-key="{key}" aria-checked="true" aria-label="{label}">'
                    f'<rect class="hit" x="{x + 10}" y="{ry - 17}" width="{w - 20}" height="32" rx="8" fill="#fff" fill-opacity="0" pointer-events="all"/>'
                    f'{ms.text(x + 24, ry + 5, label, 17, ar.WHITE, "start", "", "")}'
                    f'<rect class="swbg" x="{x + w - 66}" y="{ry - 11}" width="44" height="24" rx="12" fill="{ar.BLUE}"/>'
                    f'<circle class="swknob" cx="{x + w - 32}" cy="{ry + 1}" r="9" fill="#fff"/></g>')
    return (f'<g id="gSettings" style="display:none">{ar.glass("gSetBg", x, y, w, h, 14, 0.72)}'
            f'{ms.text(x + 24, y + 36, "Settings", 20, ar.WHITE, "start", "", ar.FW600)}'
            f'{ms.text(x + w - 24, y + 36, "prototype", 12, ar.MUTED, "end", "", "")}{"".join(rows)}</g>')


def top_controls() -> str:
    groove = button("grooveBtn", "Play or stop the groove",
                    f'{ms.rect(994, 22, 164, 28, 14, "#05080f", ar.GREEN, 1.5, ar.FO55)}'
                    f'<path id="grooveIcon" d="M1014 30l11 6 -11 6z" fill="{ar.GREEN}"/>'
                    f'{ms.text(1034, 40.5, "Play groove", 13, ar.GREEN, "start", "b", GROOVE_ID)}'
                    '<rect class="hit" x="994" y="22" width="164" height="28" rx="14" fill="#fff" fill-opacity="0" pointer-events="all"/>')
    hint = (f'<g id="gHint" pointer-events="none">{ms.text(632, 884, "Click a drum or press 1 to 4", 15, ar.MUTED, "middle", "", "")}'
            f'{ms.text(632, 906, "Space plays a groove", 15, ar.MUTED, "middle", "", "")}</g>')
    return groove + hint


PAGE_CSS = """
:root{color-scheme:dark}
html,body{margin:0;height:100%;background:#02040a}
body{display:grid;place-items:center;overflow:hidden}
#ui{display:block;width:min(100vw,calc(100vh * 1672 / 941));height:auto;touch-action:manipulation;user-select:none;-webkit-user-select:none}
.hit,.padhit{cursor:pointer}
.padhit{fill:transparent;stroke:transparent;stroke-width:3;pointer-events:all}
.padhit:hover{stroke:rgba(255,255,255,.45)}
[tabindex]:focus{outline:none}
[tabindex]:focus-visible{outline:3px solid #fff;outline-offset:3px;border-radius:6px}
.chipglow{pointer-events:none}
.mi:hover .mibg{fill-opacity:.12}
.mi.on .tick{opacity:1}
.sw .swbg,.sw .swknob{transition:fill .15s,cx .15s}
.sw[aria-checked=false] .swbg{fill:#3a4358}
.calm .dust{animation:none;opacity:0}
#gHint{transition:opacity .6s}
.used #gHint{opacity:0}
#grooveBtn text{pointer-events:none}
"""

JS = r"""
(() => {
'use strict';
const NS = 'http://www.w3.org/2000/svg';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const svg = $('#ui');
const PADS = __PADS__, GROOVE = __GROOVE__, SAMPLES = __SAMPLES__, ORB = __ORBS__, KEYS = __KEYS__, HAND = __HAND__, CYCLE = __CYCLE__;
const S = { sens: .7, vol: .8, groove: false, timers: [], sparks: true };
const KICK = { L: -9, R: 9 };
const DOT = { L: [167, 216, '#2aa8ff'], R: [167, 245, '#ff3b4a'] };

function el(name, attrs, parent) {
  const e = document.createElementNS(NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  e.setAttribute('pointer-events', 'none');
  if (parent) parent.appendChild(e);
  return e;
}
const toSvg = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
const once = (anim, node) => { anim.onfinish = () => node.remove(); return anim; };
const reduce = () => $('.sw[data-key=motion]').getAttribute('aria-checked') === 'false';

/* ---- sound: the project's recorded samples, decoded on the first gesture ---- */
let ac, master; const buffers = {};
async function initAudio() {
  if (ac) { if (ac.state === 'suspended') ac.resume(); return; }
  try {
    ac = new (window.AudioContext || window.webkitAudioContext)();
    master = ac.createGain(); master.gain.value = S.vol; master.connect(ac.destination);
    await Promise.all(Object.entries(SAMPLES).map(async ([k, uri]) => {
      buffers[k] = await ac.decodeAudioData(await (await fetch(uri)).arrayBuffer());
    }));
  } catch (err) { console.warn('Audio unavailable, the prototype continues silently.', err); }
}
function play(name) {
  if (!ac || !buffers[name]) return;
  if (ac.state === 'suspended') ac.resume();
  const src = ac.createBufferSource(); src.buffer = buffers[name]; src.connect(master); src.start();
}

/* ---- one strike: sound, rings, flash, sparks, label, hand, orb, stick ---- */
function hit(name) {
  const p = PADS[name], hand = HAND[name], g = $(`.padfx[data-pad=${name}]`);
  if (!p || !g) return;
  document.documentElement.classList.add('used');
  play(name);
  const k = .35 + .9 * S.sens, long = name === 'crash', dur = long ? 950 : 550;
  const flash = el('ellipse', { rx: p.rx, ry: p.ry, fill: p.col, opacity: 0 }, g);
  once(flash.animate([{ opacity: .42 * k }, { opacity: 0 }], { duration: long ? 550 : 340, easing: 'ease-out' }), flash);
  [[0, 10, 3.2], [90, 6, 2]].forEach(([delay, wg, wc]) => {
    const ring = el('g', { opacity: 0 }, g);
    el('ellipse', { rx: p.rx, ry: p.ry, fill: 'none', stroke: p.col, 'stroke-width': wg, 'stroke-opacity': .28, 'vector-effect': 'non-scaling-stroke' }, ring);
    el('ellipse', { rx: p.rx, ry: p.ry, fill: 'none', stroke: '#fff', 'stroke-width': wc, 'stroke-opacity': .9, 'vector-effect': 'non-scaling-stroke' }, ring);
    once(ring.animate([{ transform: 'scale(.62)', opacity: .95 * Math.min(1, k) }, { transform: 'scale(1.28)', opacity: 0 }],
      { duration: dur, delay, easing: 'cubic-bezier(.2,.7,.3,1)', fill: 'backwards' }), ring);
  });
  if (S.sparks) {
    const n = Math.round((long ? 10 : 7) * (.5 + k));
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, d = (70 + Math.random() * 80) * (long ? 1.25 : 1) * k, l = 12 + Math.random() * 12;
      const sp = el('g', { opacity: 0 }, g), c = Math.cos(a), s = Math.sin(a);
      el('line', { x1: 0, y1: 0, x2: l * c, y2: l * s, stroke: '#fff', 'stroke-width': 2.6, 'stroke-linecap': 'round' }, sp);
      el('line', { x1: .45 * l * c, y1: .45 * l * s, x2: l * c, y2: l * s, stroke: p.col, 'stroke-width': 4.4, 'stroke-opacity': .75, 'stroke-linecap': 'round' }, sp);
      once(sp.animate([{ transform: 'translate(0px,0px)', opacity: 1 }, { transform: `translate(${d * c}px,${d * s * .8}px)`, opacity: 0 }],
        { duration: long ? 700 : 450, easing: 'ease-out' }), sp);
    }
  }
  const glow = $(`.chipglow[data-pad=${name}]`);
  if (glow) glow.animate([{ opacity: .95 }, { opacity: 0 }], { duration: 500, easing: 'ease-out' });
  const dyn = $('#gDyn'), [dx, dy, dc] = DOT[hand], [ox, oy, oc] = ORB[hand];
  const halo = el('circle', { cx: dx, cy: dy, r: 7.5, fill: dc, opacity: 0 }, dyn);
  halo.style.transformOrigin = `${dx}px ${dy}px`; halo.style.transformBox = 'view-box';
  once(halo.animate([{ opacity: .7, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(2.3)' }], { duration: 400 }), halo);
  const orb = el('circle', { cx: ox, cy: oy, r: 12, fill: oc, opacity: 0 }, $('#gOrbs'));
  orb.style.transformOrigin = `${ox}px ${oy}px`; orb.style.transformBox = 'view-box';
  once(orb.animate([{ opacity: .55, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(3.8)' }], { duration: 400 }), orb);
  const stick = $('#stick' + hand);
  if (stick) stick.animate([{ transform: `rotate(${KICK[hand]}deg)` }, { transform: 'rotate(0deg)' }], { duration: 420, easing: 'cubic-bezier(.2,.8,.3,1)' });
}

/* ---- groove: the same 12 s loop as the README animation ---- */
function startGroove() {
  stopGroove(); S.groove = true;
  const run = () => {
    GROOVE.forEach((e) => S.timers.push(setTimeout(() => hit(e.pad), e.t * 1000)));
    S.timers.push(setTimeout(run, CYCLE * 1000));
  };
  run(); initAudio(); paintGroove();
}
function stopGroove() { S.timers.forEach(clearTimeout); S.timers = []; S.groove = false; paintGroove(); }
function paintGroove() {
  $('#grooveText').textContent = S.groove ? 'Stop groove' : 'Play groove';
  $('#grooveIcon').setAttribute('d', S.groove ? 'M1014 31h10v10h-10z' : 'M1014 30l11 6 -11 6z');
  $('#grooveBtn').setAttribute('aria-pressed', String(S.groove));
}
const toggleGroove = () => (S.groove ? stopGroove() : startGroove());

/* ---- buttons, menus, switches ---- */
function activate(node, fn) {
  node.addEventListener('click', fn);
  node.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); fn(e); } });
}
const menu = $('#gMenu'), settings = $('#gSettings');
const closePanels = () => { menu.style.display = 'none'; settings.style.display = 'none'; };
const toggle = (g) => { const open = g.style.display === 'none'; closePanels(); g.style.display = open ? '' : 'none'; };
activate($('#grooveBtn'), toggleGroove);
activate($('#settingsHit'), () => toggle(settings));
activate($('#camHit'), () => toggle(menu));
$('#settingsHit').setAttribute('role', 'button'); $('#settingsHit').setAttribute('tabindex', '0'); $('#settingsHit').setAttribute('aria-label', 'Settings');
$('#camHit').setAttribute('role', 'button'); $('#camHit').setAttribute('tabindex', '0'); $('#camHit').setAttribute('aria-label', 'Camera view');
$$('.mi').forEach((item) => activate(item, () => {
  $$('.mi').forEach((m) => m.classList.toggle('on', m === item));
  const label = $('#camLabel'); label.textContent = item.getAttribute('aria-label');
  label.removeAttribute('textLength'); label.removeAttribute('lengthAdjust');
  closePanels();
}));
$('.mi').classList.add('on');
const SWITCH = {
  brackets: () => '#gBrackets', trails: () => '#gTrails', scan: () => '#gScan', dust: () => '#gDust',
};
$$('.sw').forEach((sw) => activate(sw, () => {
  const on = sw.getAttribute('aria-checked') !== 'true';
  sw.setAttribute('aria-checked', String(on));
  const knob = $('.swknob', sw), bg = $('.swbg', sw), x = +bg.getAttribute('x');
  knob.setAttribute('cx', x + (on ? 34 : 10));
  const key = sw.dataset.key;
  if (SWITCH[key]) $(SWITCH[key]()).style.display = on ? '' : 'none';
  if (key === 'sparks') S.sparks = on;
  if (key === 'motion') { on ? svg.unpauseAnimations() : svg.pauseAnimations(); svg.classList.toggle('calm', !on); }
}));
document.addEventListener('pointerdown', (e) => {
  if (!e.target.closest('#gMenu,#gSettings,#camHit,#settingsHit')) closePanels();
}, true);

/* ---- sliders ---- */
function slider(id, x0, x1, start, onChange) {
  const hit = $(`#${id}Hit`), fill = $(`#${id}Fill`), knob = $(`#${id}Knob`), glow = $(`#${id}Glow`), val = $(`#${id}Val`);
  let v = start;
  const set = (nv, emit = true) => {
    v = Math.max(0, Math.min(1, nv)); const x = x0 + (x1 - x0) * v;
    fill.setAttribute('width', x - x0); knob.setAttribute('cx', x); glow.setAttribute('cx', x); val.textContent = v.toFixed(1);
    hit.setAttribute('aria-valuenow', v.toFixed(1)); if (emit) onChange(v);
  };
  const at = (e) => set((toSvg(e).x - x0) / (x1 - x0));
  hit.setAttribute('role', 'slider'); hit.setAttribute('tabindex', '0');
  hit.setAttribute('aria-valuemin', '0'); hit.setAttribute('aria-valuemax', '1'); hit.setAttribute('aria-label', id === 'sens' ? 'Sensitivity' : 'Volume');
  hit.addEventListener('pointerdown', (e) => { hit.setPointerCapture(e.pointerId); at(e); hit.onpointermove = at; });
  hit.addEventListener('pointerup', () => { hit.onpointermove = null; });
  hit.addEventListener('keydown', (e) => {
    const step = { ArrowLeft: -.1, ArrowDown: -.1, ArrowRight: .1, ArrowUp: .1 }[e.key];
    if (step) { e.preventDefault(); set(v + step); }
  });
  set(start, false);
}
slider('sens', 902, 1102, S.sens, (v) => { S.sens = v; });
slider('vol', 1445, 1598, S.vol, (v) => { S.vol = v; if (master) master.gain.value = v; });

/* ---- drums: click, tap, keys ---- */
$$('.padhit, .hit[data-pad]').forEach((h) => {
  const name = h.dataset.pad;
  h.addEventListener('pointerdown', (e) => { e.preventDefault(); initAudio(); hit(name); });
  if (h.classList.contains('hit')) { h.setAttribute('tabindex', '0'); h.setAttribute('role', 'button'); h.setAttribute('aria-label', PADS[name].name); h.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); initAudio(); hit(name); } }); }
});
addEventListener('keydown', (e) => {
  if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
  if (KEYS[e.key]) { initAudio(); hit(KEYS[e.key]); }
  else if (e.code === 'Space' && !e.target.closest('[role=button],[role=slider],[role=switch],[role=option]')) { e.preventDefault(); toggleGroove(); }
  else if (e.key === 'Escape') closePanels();
});
addEventListener('error', (e) => { document.documentElement.dataset.error = e.message; });
window.__sd = { hit, startGroove, stopGroove, state: S };
initAudio();
document.documentElement.dataset.ready = '1';
if (location.hash === '#demo') startGroove();
})();
"""


def build(photo_path: Path) -> str:
    plate_uri, blur_uri = ar.images(photo_path)
    empty = {k: [] for k in ar.PADS}
    defs = ar.defs_markup(plate_uri, blur_uri)
    layers = [
        '<use href="#plate"/>', f'<rect width="{ar.W}" height="{ar.H}" fill="url(#vig)" pointer-events="none"/>',
        f'<g id="gOrbs" pointer-events="none">{ar.orb_pulses(empty)}</g>',
        f'<g id="gTrails" pointer-events="none">{ar.trail_paths()}</g>',
        f'<g id="gBrackets" pointer-events="none">{ar.ar_brackets()}</g>',
        f'<g id="gScan" pointer-events="none">{ar.ar_scan()}</g>',
        f'<g id="gDust" pointer-events="none">{ar.ar_dust()}</g>',
        f'<g id="gPads">{pads_layer()}</g>',
        ar.labels(empty, True),
        ar.tracking_panel(empty, True), ar.stats_panel(empty), ar.logo_card(), ar.control_bar(True),
        '<g id="gDyn" pointer-events="none"></g>',
        ar.concept_chip().replace("<g>", '<g pointer-events="none">', 1),
        top_controls(), menu_layer(), settings_layer(),
    ]
    pads_js = {k: dict(name=p["name"], col=p["col"], rx=p["rx"], ry=p["ry"]) for k, p in ar.PADS.items()}
    groove = sorted(({"t": t, "pad": pad} for pad, hs in ar.groove().items() for t, _ in hs), key=lambda e: e["t"])
    orbs = {h: [x, y, c] for h, (x, y, c) in ar.ORBS.items()}
    js = (JS.replace("__PADS__", json.dumps(pads_js)).replace("__GROOVE__", json.dumps(groove)).replace("__SAMPLES__", json.dumps(samples()))
          .replace("__ORBS__", json.dumps(orbs)).replace("__KEYS__", json.dumps(KEYS)).replace("__HAND__", json.dumps(HAND)).replace("__CYCLE__", str(ar.CYCLE)))
    desc = "Interactive prototype of the SpaceDrums AR view. A design concept, not the application: no camera, no tracking."
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>SpaceDrums AR View</title>\n<meta name="description" content="{desc}">\n'
        f"<style>{ms.BASE_CSS}{ar.CSS}{PAGE_CSS}</style>\n</head>\n<body>\n"
        f'<svg id="ui" viewBox="0 0 {ar.W} {ar.H}" role="application" aria-label="SpaceDrums AR view prototype. Click a drum, press 1 to 4, or press Space for a groove.">\n'
        f"<defs>{defs}</defs>\n{''.join(layers)}\n</svg>\n"
        "<noscript>This prototype needs JavaScript for sound and interaction.</noscript>\n"
        f"<script>{js}</script>\n</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", type=Path, default=ar.SRC)
    ap.add_argument("--output", type=Path, default=OUT)
    args = ap.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(args.photo), encoding="utf-8", newline="\n")
    print(f"  {args.output}  {args.output.stat().st_size / 1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
