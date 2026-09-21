"""Phase 02, Task 02.7: camera-distance / field-of-view benchmark, visibility & pixel-size part.

Protocol: docs/protocols/camera-distance-benchmark.md. Two sub-commands:

  capture   Needs a person at a marked distance holding a stick with both hands in the box.
            Saves the raw frame, the frame with the guide overlay, and a JSON side-car
            (distance, camera height/tilt, mode, exposure, lighting) under
            data/dev-captures/distance/<label>/.

  measure   Measures apparent sizes in pixels on a captured frame: stick length (two clicked or
            given endpoints), hand height (two points), and records whether both hands + full
            stick paths stayed inside the ROI (operator's answer). Prints the Markdown row for
            the protocol's table and appends it to the label's JSON side-car.

Usage:
    python scripts/distance_benchmark.py capture --label d150 --distance-m 1.5 --camera-height-m 0.75 \
        --tilt-deg 0 --lighting L2-overhead-room-light
    python scripts/distance_benchmark.py measure --label d150 --stick 120,300,330,180 --hand 200,280,200,340 \
        --hands-inside yes --paths-inside partial --note "left tip leaves box on crash swing"
    python scripts/distance_benchmark.py measure --label d150 --interactive     # click the points
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import ROOT  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.capture import (  # noqa: E402
    CaptureSettings,
    LiveFrameSource,
    OpenCvCamera,
    Roi,
    SyntheticCamera,
)
from spacedrums.capture.backend import CameraOpenSpec  # noqa: E402
from spacedrums.capture.roi import px_to_norm_point  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import TimestampSource  # noqa: E402
from spacedrums.ui import draw_guide  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"
OUT = ROOT / "data" / "dev-captures" / "distance"


def cmd_capture(args: argparse.Namespace) -> int:
    overrides: dict[str, Any] = {"camera_profile": {"device": {}}}
    if args.backend:
        overrides["camera_profile"]["device"]["backend"] = args.backend.upper()
    cfg = load_config(args.base_config, args.camera_config, overrides=overrides)
    settings = CaptureSettings.from_config(cfg.data)
    d = OUT / args.label
    d.mkdir(parents=True, exist_ok=True)
    if args.synthetic:
        camera: Any = SyntheticCamera(width=640, height=480, fps=30)
        settings = CaptureSettings(camera_profile_id=settings.camera_profile_id, spec=CameraOpenSpec(),
                                   roi=Roi.from_rect(cfg["roi"]["px"]), nominal_fps=30,
                                   timestamp_source=TimestampSource.GRAB_RETURN, warmup_frames=2)
    else:
        camera = OpenCvCamera()
    src = LiveFrameSource(camera, settings)
    mode = src.start()
    print(f"hold still at {args.distance_m} m; capturing in {args.countdown:.0f} s ...")
    t_end = timing.now() + args.countdown
    last = None
    while timing.now() < t_end:
        f = src.next_frame(timeout=0.5)
        if f is not None:
            last = f
    src.stop()
    if last is None:
        print("no frame captured")
        return 2
    cv2.imwrite(str(d / "frame.png"), last.image_ref.array)
    cv2.imwrite(str(d / "frame_guide.png"), draw_guide(last.image_ref.array, src.roi))
    side = {
        "label": args.label, "distance_m": args.distance_m, "camera_height_m": args.camera_height_m,
        "tilt_deg": args.tilt_deg, "lighting": args.lighting, "note": args.note,
        "negotiated": mode.to_dict(), "roi_px": cfg["roi"]["px"],
        "exposure": cfg["camera_profile"]["exposure"],
        "config_hash": cfg.config_hash, "captured_at": timing.wall_clock_iso(),
        "purpose": "developer-only distance benchmark capture (Task 02.7); NOT a dataset recording",
        "measurements": [],
    }
    (d / "capture.json").write_text(json.dumps(side, indent=2), encoding="utf-8")
    print(f"saved {d / 'frame.png'} and frame_guide.png")
    return 0


def _points(text: str) -> tuple[tuple[float, float], tuple[float, float]]:
    v = [float(x) for x in text.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("expected x1,y1,x2,y2")
    return (v[0], v[1]), (v[2], v[3])


def _click_two(img, title: str) -> tuple[tuple[float, float], tuple[float, float]]:
    pts: list[tuple[float, float]] = []

    def cb(event, x, y, flags, param):  # noqa: ANN001
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 2:
            pts.append((float(x), float(y)))

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(title, cb)
    while len(pts) < 2:
        vis = img.copy()
        for p in pts:
            cv2.circle(vis, (int(p[0]), int(p[1])), 4, (0, 0, 255), -1)
        cv2.putText(vis, f"{title}: click 2 points ({len(pts)}/2)", (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 255), 2)
        cv2.imshow(title, vis)
        if cv2.waitKey(30) & 0xFF == 27:
            break
    cv2.destroyWindow(title)
    if len(pts) < 2:
        raise SystemExit("aborted")
    return pts[0], pts[1]


def cmd_measure(args: argparse.Namespace) -> int:
    d = OUT / args.label
    side = json.loads((d / "capture.json").read_text(encoding="utf-8"))
    roi = Roi.from_rect(side["roi_px"])
    img = cv2.imread(str(d / "frame.png"))
    if args.interactive:
        stick = _click_two(img, "stick (butt -> tip)")
        hand = _click_two(img, "hand (top -> bottom)")
    else:
        if not args.stick or not args.hand:
            print("give --stick and --hand or use --interactive")
            return 2
        stick, hand = args.stick, args.hand
    stick_px = math.dist(stick[0], stick[1])
    hand_px = math.dist(hand[0], hand[1])
    stick_norm = math.dist(px_to_norm_point(*stick[0], roi), px_to_norm_point(*stick[1], roi))
    row = {
        "distance_m": side["distance_m"], "camera_height_m": side["camera_height_m"],
        "tilt_deg": side["tilt_deg"], "lighting": side["lighting"],
        "resolution": f"{side['negotiated']['width']}x{side['negotiated']['height']}",
        "stick_px": round(stick_px, 1), "stick_roi_norm": round(stick_norm, 4), "hand_px": round(hand_px, 1),
        "hands_inside_roi": args.hands_inside, "stick_paths_inside_roi": args.paths_inside,
        "note": args.note, "stick_points_px": stick, "hand_points_px": hand,
        "tracking_quality": "PENDING (Phase 03, Task 03.11)",
        "measured_at": timing.wall_clock_iso(),
    }
    side.setdefault("measurements", []).append(row)
    (d / "capture.json").write_text(json.dumps(side, indent=2), encoding="utf-8")
    print("Markdown row for docs/protocols/camera-distance-benchmark.md:")
    print(f"| {row['distance_m']} | {row['camera_height_m']} / {row['tilt_deg']} | {row['resolution']} | "
          f"{row['hands_inside_roi']} | {row['stick_paths_inside_roi']} | {row['stick_px']} "
          f"({row['stick_roi_norm']:.3f} ROI-norm) | {row['hand_px']} | PENDING (03.11) | {row['note']} |")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    p.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    p.add_argument("--synthetic", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--label", required=True)
    c.add_argument("--distance-m", type=float, required=True)
    c.add_argument("--camera-height-m", type=float, required=True)
    c.add_argument("--tilt-deg", type=float, default=0.0)
    c.add_argument("--lighting", required=True)
    c.add_argument("--backend", default=None)
    c.add_argument("--countdown", type=float, default=5.0)
    c.add_argument("--note", default="")
    c.set_defaults(func=cmd_capture)
    m = sub.add_parser("measure")
    m.add_argument("--label", required=True)
    m.add_argument("--stick", type=_points, default=None)
    m.add_argument("--hand", type=_points, default=None)
    m.add_argument("--hands-inside", choices=["yes", "no", "partial"], default="unrecorded")
    m.add_argument("--paths-inside", choices=["yes", "no", "partial"], default="unrecorded")
    m.add_argument("--interactive", action="store_true")
    m.add_argument("--note", default="")
    m.set_defaults(func=cmd_measure)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
