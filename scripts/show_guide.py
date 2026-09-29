"""Phase 02, Task 02.6: live "stand here" guide window (prototype UI) and screenshot.

Runs ``LiveFrameSource`` with the camera config, draws the guide (ROI box, hands band,
instruction, capture-stats line with drops always visible) and shows it in an OpenCV window for
``--duration`` seconds (press q to quit early). The live window mirrors only the camera image and
draws the guide on it with readable text. ``--screenshot`` saves the last frame's guide in the
original camera orientation (evidence for the gate record). ``--no-window`` renders without a
window (headless screenshot).

Usage:
    python scripts/show_guide.py --duration 15 --screenshot docs/figures/phase-02/guide-hw01.png
    python scripts/show_guide.py --synthetic --no-window --screenshot out.png   # self-test
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
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
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import TimestampSource  # noqa: E402
from spacedrums.ui import draw_guide, guide_status_lines  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"
WINDOW = "Space Drums - stand here (prototype)"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    p.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    p.add_argument("--backend", default=None)
    p.add_argument("--exposure", default=None, help="AUTO or MANUAL:<value>")
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--band", default="0.45,0.75", help="hands band y0,y1 (ROI-normalized, y down)")
    p.add_argument("--screenshot", type=Path, default=None)
    p.add_argument("--no-window", action="store_true")
    p.add_argument("--synthetic", action="store_true")
    args = p.parse_args(argv)

    overrides: dict[str, Any] = {"camera_profile": {"device": {}}}
    if args.backend:
        overrides["camera_profile"]["device"]["backend"] = args.backend.upper()
    if args.exposure:
        mode, _, value = args.exposure.partition(":")
        overrides["camera_profile"]["exposure"] = {"mode": mode.upper(),
                                                   "value": float(value) if value else None}
    cfg = load_config(args.base_config, args.camera_config, overrides=overrides)
    settings = CaptureSettings.from_config(cfg.data)
    band = tuple(float(v) for v in args.band.split(","))
    if args.synthetic:
        camera: Any = SyntheticCamera(width=640, height=480, fps=30, paced=True)
        settings = CaptureSettings(camera_profile_id=settings.camera_profile_id, spec=CameraOpenSpec(),
                                   roi=Roi.from_rect(cfg["roi"]["px"]), nominal_fps=30,
                                   timestamp_source=TimestampSource.GRAB_RETURN, warmup_frames=2)
    else:
        camera = OpenCvCamera()
    src = LiveFrameSource(camera, settings)
    mode = src.start()
    print(f"negotiated {mode.backend} {mode.width}x{mode.height} {mode.fourcc} fps_prop={mode.fps_prop} "
          f"(advertised) ROI {src.roi.as_tuple()}")
    last = None
    try:
        if not args.no_window:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        t_end = timing.now() + args.duration
        while timing.now() < t_end:
            f = src.next_frame(timeout=0.5)
            if f is None:
                if src._queue.closed:
                    break
                continue
            lines = guide_status_lines(src.stats(), mode)
            last = (f.image_ref.array, lines)
            if not args.no_window:
                cv2.imshow(WINDOW, draw_guide(f.image_ref.array, src.roi, band=band, status_lines=lines,
                                              mirror=True))
                if cv2.pollKey() & 0xFF == ord("q"):
                    break
        stats = src.stats()
    finally:
        src.stop()
        if not args.no_window:
            cv2.destroyAllWindows()
            cv2.waitKey(1)
    print(f"capture stats: {stats}")
    if args.screenshot is not None and last is not None:
        frame, lines = last
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.screenshot), draw_guide(frame, src.roi, band=band, status_lines=lines))
        print(f"screenshot written: {args.screenshot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
