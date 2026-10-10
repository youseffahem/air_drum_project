"""Offline preview of the full-kit layout: pad coordinates, clearances and measured fingertip reach.

Renders the kit through the same StageRenderer the live demo uses, so the picture is the real hit
geometry. Without --session the background is a blank synthetic ROI (pass --synthetic to confirm that
is intended); with --frame a saved camera frame is used; with --session DIR the measured fingertips
and commits from that developer session's observations.jsonl are overlaid and every pad gets a reach
verdict (measured fingertips above its top edge AND inside it, within its x span).

Usage:
  python scripts/preview_kit_layout.py --synthetic --output OUT_DIR
  python scripts/preview_kit_layout.py --session data/dev-product/<session> --output OUT_DIR
  python scripts/preview_kit_layout.py --pads kit-layout.yaml --frame frame.png --output OUT_DIR
Writes kit-preview.png and kit-preview.json. No camera, window or audio device is opened.
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

from spacedrums.app import play  # noqa: E402
from spacedrums.calib.reach import ReachSettings  # noqa: E402
from spacedrums.capture import Roi  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.geometry.kit_layout import (  # noqa: E402
    kit_clearance_failures,
    kit_layout,
    pad_clearance_px,
)
from spacedrums.ui.layout_preview import LayoutPreview, reach_report  # noqa: E402
from spacedrums.ui.stage import StageRenderer  # noqa: E402


def read_session(directory: Path):
    tips = {h: [] for h in HandId}
    hits: dict[str, int] = {}
    with (directory / "observations.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            for e in row["endpoints"]:
                if e.get("kind") == "MEASURED" and e.get("tip"):
                    tips[HandId(e["hand_id"])].append(tuple(e["tip"]))
            for c in row["commits"]:
                hits[c["zone_id"]] = hits.get(c["zone_id"], 0) + 1
    return tips, hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pads", type=Path, help="saved kit-layout.yaml (default: the configured full kit)")
    ap.add_argument("--frame", type=Path, help="background camera frame (BGR image, 640x480)")
    ap.add_argument("--session", type=Path, help="developer session directory with observations.jsonl")
    ap.add_argument("--synthetic", action="store_true", help="acknowledge a blank synthetic background")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not (args.frame or args.session or args.synthetic):
        ap.error("pass --synthetic to render on a blank ROI, or --frame / --session")

    cfg = play.play_config(demo=True, kit="full", kit_layout=args.pads)
    pads = cfg["product"]["developer_demo"]["pads"]
    roi_px = tuple(cfg["roi"]["px"])
    roi = Roi.from_rect(roi_px)
    settings = ReachSettings(**cfg["product"].get("reach", {}))
    size = (roi.w, roi.h)
    kit_layout(pads)
    failures = kit_clearance_failures(pads, size, settings.horizontal_gap_px, settings.vertical_gap_px)

    frame = cv2.imread(str(args.frame)) if args.frame else np.full((480, 640, 3), 70, np.uint8)
    if frame is None or frame.shape[:2] != (480, 640):
        raise SystemExit("--frame must be a readable 640x480 image")
    registry = ZoneRegistry.from_config(cfg["zones"])
    evidence = {h: SimpleNamespace(kind="MISSING", tip=None) for h in HandId}
    result = SimpleNamespace(sample=SimpleNamespace(t_capture=1.0), commits=[])
    renderer = StageRenderer()
    img = renderer.render(frame, roi, registry, evidence, result)

    preview = LayoutPreview(pads, lambda _: None)
    verdict = "FAIL" if failures else "OK"
    preview.message = f"{verdict}: {len(pads)} pads, {len(failures)} clearance failure(s)"
    if args.session:
        tips, hits = read_session(args.session)
        for hand in HandId:
            preview.tips[hand].extend(tips[hand][-6000:])
        preview.hits.update(hits)
    preview.draw(img, renderer, roi, frame.shape[1])

    report = {}
    all_tips = np.vstack([preview.display_tips(h) for h in HandId]) if args.session else np.empty((0, 2))
    if args.session:
        report = reach_report(pads, all_tips)
    tip_stats = {
        str(h): {"n": len(preview.tips[h]),
                 "display_x_p5_p50_p95": np.percentile(preview.display_tips(h)[:, 0], [5, 50,
                 95]).round(3).tolist(),
                 "y_p5_p50_p95": np.percentile(preview.display_tips(h)[:, 1], [5, 50, 95]).round(3).tolist()}
        for h in HandId if len(preview.tips[h])
    }
    out = {
        "roi_px": list(roi_px),
        "floors": {"min_width_px": settings.min_width_px, "min_height_px": settings.min_height_px,
                   "horizontal_gap_px": settings.horizontal_gap_px,
                   "vertical_gap_px": settings.vertical_gap_px},
        "pads": [{**p, "px": [round(p["width"] * roi.w), round(p["height"] * roi.h)],
                  "top_edge_px": round(p["y"] * roi.h)} for p in pads],
        "clearance_failures": failures,
        "tightest_pairs_px": sorted(
            ({"pair": [a["zone_id"], b["zone_id"]], "dx": round(pad_clearance_px(a, b, size)[0], 1),
              "dy": round(pad_clearance_px(a, b, size)[1], 1)}
             for i, a in enumerate(pads) for b in pads[i + 1:]),
            key=lambda r: -max(r["dx"], r["dy"]))[-6:],
        "session": str(args.session) if args.session else None,
        "tips": tip_stats,
        "reach": report,
        "hits": dict(preview.hits),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output / "kit-preview.png"), img)
    (args.output / "kit-preview.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("clearance_failures", "tightest_pairs_px", "tips", "reach",
        "hits")}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
