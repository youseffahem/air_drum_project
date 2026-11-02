"""Offline snapshot of the AR view for visual review against the reference screen.

Renders the real AR view (GPU kit, glow, HUD, control bar) over a saved camera frame with SYNTHETIC
stick evidence and, optionally, a SYNTHETIC committed hit, then writes the frame and a side-by-side with
the reference image. A 640x480 tracking frame is upscaled to the 960x720 native window and its sides are
filled by reflection to make the 1280x720 native canvas; the sides are therefore not real camera pixels.
No camera, window or audio device is opened.

Usage:
  python scripts/render_ar_snapshot.py --frame docs/presentation/assets/recorded-camera-frame-140.png \
      --reference docs/design/ar-reference.png --output data/ar-snapshots
  python scripts/render_ar_snapshot.py --frame F.png --kit full --hit snare --hit-age 0.06 --output OUT
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spacedrums.capture import Roi  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.contracts.perception import EndpointEvidence  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.geometry.kit_layout import kit_layout  # noqa: E402
from spacedrums.geometry.reference_kit import reference_kit_layout  # noqa: E402
from spacedrums.ui.ar import ARView, DisplayMap, UiStatus  # noqa: E402

NATIVE_CROP = [159, 0, 960, 720]
# SYNTHETIC sticks (ROI units, camera coordinates: x is mirrored on screen), raised as on the reference.
STICKS = {HandId.LEFT: ((0.66, 0.70), (0.60, 0.28)), HandId.RIGHT: ((0.36, 0.70), (0.33, 0.24))}


def native_canvas(frame):
    if frame.shape[:2] == (720, 1280):
        return frame
    big = cv2.resize(frame, (960, 720), interpolation=cv2.INTER_LINEAR)
    return cv2.copyMakeBorder(big, 0, 0, 159, 161, cv2.BORDER_REFLECT)


def evidence(t, sticks):
    return {
        h: EndpointEvidence(0, t, h, "MEASURED", "SYNTHETIC", tip=tip, origin=origin, confidence=1.0)
        for h, (origin, tip) in sticks.items()
    }


def render(frame, *, kit="reference", hit=None, hit_age=0.06, viewpoint="front", status=None):
    if kit == "full":
        import yaml

        pads = yaml.safe_load((ROOT / "configs/demo.fullkit.candidate.yaml").read_text())
        registry = ZoneRegistry.from_config(kit_layout(pads["product"]["developer_demo"]["pads"]))
    else:
        registry = ZoneRegistry.from_config(reference_kit_layout())
    canvas = native_canvas(frame)
    dmap = DisplayMap.native(1280, 720, NATIVE_CROP, 640)
    roi = Roi(0, 0, 640, 480)
    view = ARView()
    view.controls.viewpoint = viewpoint
    status = status or UiStatus(fps=30.0, latency_ms=28.0)
    t0 = 10.0
    trail = [(t0 - hit_age - 0.2 + 0.03 * i) for i in range(8)]
    for i, t in enumerate(trail):  # a short downward swing builds the comet trails
        moved = {h: (o, (tip[0], tip[1] - 0.05 + 0.006 * i)) for h, (o, tip) in STICKS.items()}
        view.render(
            canvas,
            roi,
            registry,
            evidence(t, moved),
            SimpleNamespace(commits=[]),
            t=t,
            dmap=dmap,
            status=status,
        )
    if hit:
        t = t0 - hit_age
        commit = SimpleNamespace(zone_id=hit, hand_id=HandId.RIGHT, gain=1.0)
        view.render(
            canvas,
            roi,
            registry,
            evidence(t, STICKS),
            SimpleNamespace(commits=[commit]),
            t=t,
            dmap=dmap,
            status=status,
        )
    img = view.render(
        canvas,
        roi,
        registry,
        evidence(t0, STICKS),
        SimpleNamespace(commits=[]),
        t=t0,
        dmap=dmap,
        status=status,
    )
    info = {
        "renderer": view.info(),
        "timings_ms": view.timings,
        "kit": kit,
        "hit": hit,
        "viewpoint": viewpoint,
        "provenance": "SYNTHETIC sticks and hit over a saved frame; reflected sides",
    }
    view.release()
    return img, info


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--frame", type=Path, required=True)
    p.add_argument("--reference", type=Path)
    p.add_argument("--kit", choices=("reference", "full"), default="reference")
    p.add_argument("--hit", help="zone id to show a committed hit on (e.g. snare, crash_ride)")
    p.add_argument("--hit-age", type=float, default=0.06)
    p.add_argument("--viewpoint", choices=("front", "high", "low"), default="front")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    frame = cv2.imread(str(args.frame))
    if frame is None:
        p.error(f"cannot read {args.frame}")
    img, info = render(frame, kit=args.kit, hit=args.hit, hit_age=args.hit_age, viewpoint=args.viewpoint)
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output / "ar-snapshot.png"), img)
    if args.reference:
        ref = cv2.imread(str(args.reference))
        if ref is None:
            p.error(f"cannot read {args.reference}")
        ref = cv2.resize(ref, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(args.output / "ar-side-by-side.png"), np.vstack((ref, img)))
    (args.output / "ar-snapshot.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
