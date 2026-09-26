"""Render a calibration for review (Task 14.4 evidence: screenshots).

    python scripts/render_calibration.py --calibration <file>.calib.yaml --output-dir <dir> \\
        [--frame data/dev-captures/swing-L2-exp-5/frame_00050.png]

Writes ``layout.png`` (calibrated zones over the frame, the Phase 04 template in grey, the reach
envelope) and ``review-placement.png`` / ``review-validation.png`` (the wizard's review screens drawn
from the stored results with ``ui.wizard_views``). The background frame is only context; the
calibration's provenance label is printed on every image (a SYNTHETIC calibration stays SYNTHETIC).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from spacedrums.calib import load_calibration
from spacedrums.capture import Roi
from spacedrums.geometry import Ellipse, ZoneRegistry
from spacedrums.ui import WizardView, draw_wizard


def _px(p, roi: Roi) -> tuple[int, int]:
    return (int(round(roi.x + p[0] * (roi.w - 1))), int(round(roi.y + p[1] * (roi.h - 1))))


def template_outlines(img: np.ndarray, roi: Roi, registry: ZoneRegistry) -> None:
    for zone in registry:
        if isinstance(zone.shape, Ellipse):
            axes = (max(1, round(zone.shape.rx * roi.w)), max(1, round(zone.shape.ry * roi.h)))
            cv2.ellipse(
                img,
                _px(zone.shape.center, roi),
                axes,
                float(np.degrees(zone.shape.angle_rad)),
                0,
                360,
                (150, 150, 150),
                1,
                cv2.LINE_AA,
            )
        else:
            pts = np.asarray([_px(p, roi) for p in zone.shape.points], np.int32)
            cv2.polylines(img, [pts], True, (150, 150, 150), 1, cv2.LINE_AA)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibration", type=Path, required=True)
    ap.add_argument("--frame", type=Path, default=None, help="background frame (context only)")
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    calib = load_calibration(args.calibration)
    d = calib.doc
    roi = Roi.from_rect(d["roi"]["px"])
    w, h = d["camera"]["resolution_px"]
    frame = cv2.imread(str(args.frame)) if args.frame else None
    if frame is None:
        frame = np.full((h, w, 3), 40, np.uint8)
    registry = ZoneRegistry.from_config(d["layout"]["zones"])
    fit = d["layout"]["fit"]
    label = f"{d['provenance']['kind']} | {d['calibration_id']} | {calib.hash[:19]}..."
    args.output_dir.mkdir(parents=True, exist_ok=True)
    layout = draw_wizard(
        frame,
        roi,
        WizardView(
            4,
            6,
            "Calibrated layout",
            "SAVED",
            lines=(
                label,
                f"{fit['mode']} fit: scale {fit['scale']:.3f}, shift ({fit['translate'][0]:+.3f}, "
                f"{fit['translate'][1]:+.3f}); grey = Phase 04 template",
            ),
            envelope=tuple(d["reach_envelope"]["box"]) if d["reach_envelope"]["box"] else None,
            registry=registry,
        ),
    )
    template_outlines(layout, roi, ZoneRegistry.from_config(d["layout"]["template"]["zones"]))
    cv2.imwrite(str(args.output_dir / "layout.png"), layout)
    placement = draw_wizard(
        frame,
        roi,
        WizardView(
            4,
            6,
            "Zone placement",
            "REVIEW",
            lines=(
                label,
                f"envelope points {d['reach_envelope']['n_points']} | overlap "
                f"{'OK' if d['layout']['checks']['overlap']['passed'] else 'BLOCKED'} | near pairs "
                f"{len(d['layout']['checks']['overlap']['near_pairs'])} | "
                f"nudges {len(d['layout']['nudges'])}",
            ),
            keys="ENTER accept | r retry | f use default | n next zone | i/j/k/l nudge | s sound",
            ok=True,
            envelope=tuple(d["reach_envelope"]["box"]) if d["reach_envelope"]["box"] else None,
            registry=registry,
            highlight_zone=d["layout"]["zones"][0]["zone_id"],
        ),
    )
    cv2.imwrite(str(args.output_dir / "review-placement.png"), placement)
    rows = "  ".join(f"{r['zone_id']} {r['detected']}/{r['cued']}" for r in d["validation"]["per_zone"])
    validation = draw_wizard(
        frame,
        roi,
        WizardView(
            5,
            6,
            "Test strikes (Arm A)",
            "REVIEW",
            lines=(
                label,
                rows or "validation SKIPPED",
                f"label {d['validation']['label']} | passed {d['validation']['passed']}",
            ),
            keys="ENTER accept | r retry | p redo placement | v skip",
            ok=d["validation"]["passed"],
            registry=registry,
        ),
    )
    cv2.imwrite(str(args.output_dir / "review-validation.png"), validation)
    print(f"[render] {args.output_dir} ({label})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
