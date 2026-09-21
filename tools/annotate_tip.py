"""Minimal stick-tip annotation tool (Phase 03, Task 03.10): the manual reference for the tip benchmark.

A person clicks the visible stick tip per hand on a stratified sample of dev-capture frames. The
tool is deliberately small: one OpenCV window, keyboard-driven, appends one JSON line per
(frame, hand) to ``data/dev-annotations/<capture>/tips.jsonl`` (git-ignored, developer-only).

Sampling (``--every``, ``--offset``): every N-th frame (uniform in time = stratified over the swing
phases and therefore over speed); ``--offset`` selects a disjoint subset for the re-annotation
agreement check (Task 03.10: "inter-annotator agreement on a re-annotated subset").

Keys:  left click = tip of the hand named in the title (LEFT first, then RIGHT)   u = undo the last
click   s = skip this hand (tip not visible)   n = next frame   q = quit (file is flushed per line).

Record format (one line per (frame, hand)):
    {"capture", "frame_id", "t_capture", "hand_id", "tip_px": [x, y] (full-frame), "tip_norm": [x, y]
     (ROI-normalized), "skipped": bool, "annotator", "annotated_at", "tool_version"}

``--synthetic`` writes ``tips.SYNTHETIC.jsonl`` from the *GEOM estimate* of a synthetic frame set; it
exists only so the benchmark's reference path can be self-tested (``--allow-synthetic-reference``).
The file name carries SYNTHETIC and every line ``"synthetic": true``; the benchmark refuses it by
default. It is never a reference for a real measurement (integrity I-4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _devcapture import DEV_CAPTURES, iter_views, load_dev_capture  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.capture import Roi, px_to_norm_point  # noqa: E402

TOOL_VERSION = "annotate_tip/0.1"
ANNOTATIONS = ROOT / "data" / "dev-annotations"
HANDS = ("LEFT", "RIGHT")


def sample_frame_ids(n_frames: int, every: int, offset: int) -> list[int]:
    if every < 1 or offset < 0 or offset >= every:
        raise ValueError("every >= 1 and 0 <= offset < every required")
    return list(range(offset, n_frames, every))


def make_record(capture: str, frame_id: int, t_capture: float, hand_id: str,
                tip_px: tuple[float, float] | None, roi: Roi, annotator: str,
                synthetic: bool = False) -> dict[str, Any]:
    rec: dict[str, Any] = {"capture": capture, "frame_id": int(frame_id), "t_capture": float(t_capture),
                           "hand_id": hand_id, "tip_px": None, "tip_norm": None, "skipped": tip_px is None,
                           "annotator": annotator, "annotated_at": timing.wall_clock_iso(),
                           "tool_version": TOOL_VERSION}
    if tip_px is not None:
        rec["tip_px"] = [float(tip_px[0]), float(tip_px[1])]
        rec["tip_norm"] = list(px_to_norm_point(tip_px[0], tip_px[1], roi))
    if synthetic:
        rec["synthetic"] = True
    return rec


def annotate_interactive(capture: str, every: int, offset: int, annotator: str, out_path: Path) -> int:
    cap = load_dev_capture(capture)
    ids = set(sample_frame_ids(len(cap), every, offset))
    roi = cap.roi
    out_path.parent.mkdir(parents=True, exist_ok=True)
    win = f"annotate_tip - {capture}"
    cv2.namedWindow(win)
    state: dict[str, Any] = {"click": None}

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            state["click"] = (float(x), float(y))

    cv2.setMouseCallback(win, on_mouse)
    written = 0
    with out_path.open("a", encoding="utf-8") as fh:
        for view in iter_views(cap):
            fid = view.sample.frame_id
            if fid not in ids:
                continue
            for hand in HANDS:
                state["click"] = None
                while True:
                    img = view.full.copy()
                    cv2.rectangle(img, (roi.x, roi.y), (roi.x1, roi.y1), (200, 200, 200), 1)
                    cv2.putText(img, f"frame {fid}  click the {hand} stick tip   (s skip, n next, q quit)",
                                (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                    if state["click"] is not None:
                        cv2.circle(img, (int(state["click"][0]), int(state["click"][1])), 5, (0, 0, 255), 2)
                    cv2.imshow(win, img)
                    key = cv2.waitKey(30) & 0xFF
                    if state["click"] is not None and key == ord("n"):
                        rec = make_record(capture, fid, view.sample.t_capture, hand, state["click"], roi,
                                          annotator)
                        fh.write(json.dumps(rec) + "\n")
                        fh.flush()
                        written += 1
                        break
                    if key == ord("u"):
                        state["click"] = None
                    elif key == ord("s"):
                        fh.write(json.dumps(make_record(capture, fid, view.sample.t_capture, hand, None, roi,
                                                        annotator)) + "\n")
                        fh.flush()
                        written += 1
                        break
                    elif key == ord("q"):
                        cv2.destroyWindow(win)
                        return written
    cv2.destroyWindow(win)
    return written


def write_synthetic(out_dir: Path) -> Path:
    """Self-test file from the synthetic benchmark scene: SYNTHETIC in the name and in every line."""
    from benchmark_tip_methods import _SynthCap
    from hands_landmark_check import StubBackend, _iter_synthetic

    from spacedrums.config import load_config
    from spacedrums.contracts import HandId, TipMethod
    from spacedrums.hands import HandLandmarker, HandLandmarkerSettings
    from spacedrums.stick import StickSettings, make_tip_estimator

    cfg = load_config(ROOT / "configs" / "example.candidate.yaml",
                      ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml")
    roi = Roi.from_rect(cfg["roi"]["px"])
    cap = _SynthCap(roi)
    lm = HandLandmarker(HandLandmarkerSettings.from_config(cfg.data), backend=StubBackend())
    est = make_tip_estimator(TipMethod.GEOM, StickSettings.from_config(cfg.data))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tips.SYNTHETIC.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for view in _iter_synthetic(cap):
            res = lm.detect(view)
            for hand in HANDS:
                obs = res.left if hand == "LEFT" else res.right
                so = est.estimate(view, obs)
                tip = None
                if so.present:
                    # offset by a couple of pixels: a fake "click" that differs from the estimate
                    tip = (roi.x + so.tip[0] * roi.w + 2.0, roi.y + so.tip[1] * roi.h - 1.0)
                rec = make_record("synthetic", view.sample.frame_id, view.sample.t_capture, hand, tip, roi,
                                  "synthetic-self-test", synthetic=True)
                fh.write(json.dumps(rec) + "\n")
    assert HandId.LEFT is HandId("LEFT")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capture", help="dev capture name under data/dev-captures/")
    ap.add_argument("--every", type=int, default=10, help="annotate every N-th frame")
    ap.add_argument("--offset", type=int, default=0,
                    help="phase of the sampling (disjoint subsets for agreement)")
    ap.add_argument("--annotator", default="owner")
    ap.add_argument("--out", type=Path, default=None,
                    help="output file (default data/dev-annotations/<capture>/tips.jsonl)")
    ap.add_argument("--synthetic", action="store_true", help="write the SYNTHETIC self-test file and exit")
    ap.add_argument("--synthetic-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.synthetic:
        path = write_synthetic(args.synthetic_dir or (ANNOTATIONS / "synthetic"))
        print(f"wrote {path} (SYNTHETIC; never a reference)")
        return 0
    if not args.capture:
        avail = sorted(p.name for p in DEV_CAPTURES.iterdir()) if DEV_CAPTURES.exists() else []
        print(f"--capture required; available: {avail}")
        return 2
    out = args.out or (ANNOTATIONS / args.capture / "tips.jsonl")
    n = annotate_interactive(args.capture, args.every, args.offset, args.annotator, out)
    print(f"wrote {n} records to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
