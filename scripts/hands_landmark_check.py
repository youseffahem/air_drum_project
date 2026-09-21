"""Phase 03, Tasks 03.1 + 03.2: hand-landmark wrapper and LEFT/RIGHT identity check on dev captures.

Runs ``spacedrums.hands.HandLandmarker`` over one or more developer-only dev captures
(``data/dev-captures/<name>/``, Phase 02 ``exposure_blur_check.py record`` format) replayed with
their recorded ``t_capture`` and writes an experiment log with the Task 03.1 evidence:

* per frame: processing time of the estimator call, number of detections, per-hand presence and
  handedness score (``per_frame.<capture>.json``); every emitted ``HandObservation`` as JSON
  (``hand_observations.<capture>.jsonl``), each validated against ``hand-observation.schema.json``;
* per capture: frames with LEFT / RIGHT / both present (**N reported, not targeted**), detections
  histogram, label collisions and unknown labels (not emitted), timestamp bumps, whether the
  estimator returned landmark visibility at all, processing-time p50 / p95 / max (all frames and
  excluding the first ``--warmup`` frames), mean wrist x per emitted ``hand_id`` (which image side
  each label lands on — input to the owner's anatomical handedness check);
* one overlay PNG per capture (frame with the most detections) for the qualitative check;
* (Task 03.2) identity metrics per capture: label-override / continuity-override / identity-jump
  event counts and rates, ambiguous frames, and every event as JSON
  (``identity_events.<capture>.jsonl``). ``--identity-mode RAW`` runs the Task 03.1 label-only
  baseline for comparison. Deliberate hand crossings need a dedicated dev capture (PENDING).

Usage:
    python scripts/hands_landmark_check.py --capture swing-L2-exp-5 --capture swing-L2-exp-6
    python scripts/hands_landmark_check.py --capture swing-L2-exp-5 --running-mode IMAGE
    python scripts/hands_landmark_check.py --capture swing-L2-exp-5 --identity-mode RAW
    python scripts/hands_landmark_check.py --synthetic          # self-test, no model, no captures

The synthetic mode uses a deterministic stub backend (no MediaPipe) so ``tests/scripts/`` can run it
anywhere; its numbers are labelled synthetic in the run description and are never evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _devcapture import DEV_CAPTURES, DevCapture, iter_views, load_dev_capture  # noqa: E402
from _runlog import ROOT, RunLog  # noqa: E402

from spacedrums.capture import Roi, crop_roi, norm_to_px  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import FrameSample, FrameView, HandId, ImageRef, TimestampSource  # noqa: E402
from spacedrums.contracts import schema as contract_schema  # noqa: E402
from spacedrums.hands import (  # noqa: E402
    HandLandmarker,
    HandLandmarkerSettings,
    HandsFrameResult,
    RawDetection,
)

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"


# ----------------------------------------------------------------------------- synthetic


class StubBackend:
    """Deterministic backend for the self-test: no model, fixed native landmarks."""

    backend_id = "stub-hand-backend@0"
    library_version = "stub"

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _hand(cx: float, cy: float) -> np.ndarray:
        pts = np.zeros((21, 2))
        for i in range(21):
            pts[i] = (cx + 0.01 * (i % 5) - 0.02, cy - 0.012 * (i // 5))
        return pts

    def detect(self, image_rgb: np.ndarray, timestamp_ms: int) -> list[RawDetection]:
        self.calls += 1
        k = self.calls - 1
        if k < 10:  # Task 03.1 scenario: static hands, one collision, one unknown label
            out = [RawDetection(self._hand(0.3, 0.8), "Right", 0.9)]
            if k % 2 == 1:
                out.append(RawDetection(self._hand(0.7, 0.8), "Left", 0.85))
            if k == 7:  # a label collision: two "Right"
                out.append(RawDetection(self._hand(0.5, 0.5), "Right", 0.4))
            if k == 9:
                out.append(RawDetection(self._hand(0.5, 0.5), "Unknown", 0.7))
            return out
        # Task 03.2 scenario (SYNTHETIC crossing): RIGHT moves 0.3 -> 0.7, LEFT 0.7 -> 0.3 over 20
        # frames; the estimator's labels flip on frames 15, 16 and 24 (label noise).
        u = (k - 10) / 19
        xr, xl = 0.3 + 0.4 * u, 0.7 - 0.4 * u
        flip = k in (15, 16, 24)
        return [RawDetection(self._hand(xr, 0.8), "Left" if flip else "Right", 0.8 if flip else 0.9),
                RawDetection(self._hand(xl, 0.8), "Right" if flip else "Left", 0.8 if flip else 0.9)]

    def close(self) -> None:
        pass


class _SyntheticCapture:
    """Thirty in-memory frames shaped like a dev capture (for ``--synthetic`` only)."""

    name = "synthetic"

    def __init__(self, roi: Roi, n: int = 30) -> None:
        self.dir = Path(".")
        self.roi = roi
        self.meta = {"lighting": "synthetic", "exposure": None, "roi_px": list(roi.as_tuple())}
        self.samples = []
        for i in range(n):
            self.samples.append(FrameSample(
                frame_id=i, t_capture=100.0 + i / 30.0, t_frame_available=100.0 + i / 30.0 + 0.001,
                timestamp_source=TimestampSource.REPLAY, frame_size_px=(640, 480), roi_px=roi.as_tuple(),
                image_ref=ImageRef.memory(np.full((480, 640, 3), 90, np.uint8)),
                camera_profile_id="synthetic", dropped_since_last=0))

    def __len__(self) -> int:
        return len(self.samples)


def _iter_synthetic(cap: _SyntheticCapture):
    for s in cap.samples:
        full = s.image_ref.array
        yield FrameView(sample=s, roi=crop_roi(full, cap.roi), full=full)


# ----------------------------------------------------------------------------- helpers


def _pct(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def _rate(count: int, denominator: int) -> float | None:
    return count / denominator if denominator else None


def _timing_stats(vals: list[float]) -> dict[str, Any]:
    return {"n": len(vals), "p50_s": _pct(vals, 50), "p95_s": _pct(vals, 95),
            "max_s": float(max(vals)) if vals else None, "mean_s": float(np.mean(vals)) if vals else None}


def _draw_overlay(full: np.ndarray, roi: Roi, res: HandsFrameResult, title: str) -> np.ndarray:
    img = full.copy()
    cv2.rectangle(img, (roi.x, roi.y), (roi.x1, roi.y1), (200, 200, 200), 1)
    colors = {HandId.LEFT: (0, 200, 255), HandId.RIGHT: (255, 120, 0)}
    assigned: dict[int, HandId] = {}
    if res.identity is not None:
        assigned = {a.candidate.index: h for h, a in res.identity.assignments.items()}
    for i, d in enumerate(res.detections):
        hid = assigned.get(i)  # Task 03.2 assigned identity (None: not emitted)
        col = colors.get(hid, (128, 128, 128)) if hid is not None else (128, 128, 128)
        px, py = norm_to_px(d.landmarks[:, 0], d.landmarks[:, 1], roi)
        for x, y in zip(px, py, strict=True):
            cv2.circle(img, (int(round(x)), int(round(y))), 3, col, -1)
        bx, by = norm_to_px(d.bbox[0], d.bbox[1], roi)
        bw, bh = d.bbox[2] * roi.w, d.bbox[3] * roi.h
        cv2.rectangle(img, (int(bx), int(by)), (int(bx + bw), int(by + bh)), col, 1)
        tag = f"{d.label}->{hid.value if hid else 'none'} {d.score:.2f}"
        if res.identity is not None and res.identity.ambiguous:
            tag += " AMBIGUOUS"
        cv2.putText(img, tag, (int(bx), max(12, int(by) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)
    cv2.putText(img, title, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return img


# ----------------------------------------------------------------------------- per capture


def run_capture(run: RunLog, landmarker: HandLandmarker, cap: DevCapture | _SyntheticCapture,
                views, *, warmup: int, overlay: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    schema_errors = 0
    n_hist: dict[str, int] = {}
    wrist_x: dict[str, list[float]] = {"LEFT": [], "RIGHT": []}
    best: tuple[int, HandsFrameResult, np.ndarray] | None = None
    obs_path = run.dir / f"hand_observations.{cap.name}.jsonl"
    ev_path = run.dir / f"identity_events.{cap.name}.jsonl"
    start_counters = landmarker.counters.to_dict()
    start_ident = landmarker.identity.counters.to_dict()
    ambiguous_frames = 0
    with obs_path.open("w", encoding="utf-8") as fh, ev_path.open("w", encoding="utf-8") as fe:
        for view in views:
            res = landmarker.detect(view)
            if res.identity is not None:
                ambiguous_frames += int(res.identity.ambiguous)
                for e in res.identity.events:
                    fe.write(json.dumps(e.to_dict()) + "\n")
            for o in res.observations:
                d = o.to_dict()
                errs = contract_schema.errors("hand-observation", d)
                if errs:
                    schema_errors += 1
                    print(f"  SCHEMA ERROR frame {o.frame_id} {o.hand_id}: {errs}")
                fh.write(json.dumps(d) + "\n")
                if o.present and o.landmarks is not None:
                    wrist_x[str(o.hand_id)].append(o.landmarks[0][0])
            n_hist[str(res.n_detected)] = n_hist.get(str(res.n_detected), 0) + 1
            rows.append({
                "frame_id": view.sample.frame_id, "t_capture": view.sample.t_capture,
                "processing_s": res.processing_s, "n_detected": res.n_detected,
                "left_present": res.left.present, "right_present": res.right.present,
                "left_score": res.left.handedness_score, "right_score": res.right.handedness_score,
                "n_not_emitted": res.n_not_emitted, "timestamp_bumped": res.timestamp_bumped,
                "identity_ambiguous": bool(res.identity.ambiguous) if res.identity is not None else None,
                "identity_margin": res.identity.margin if res.identity is not None else None,
                "identity_events": ([str(e.kind) for e in res.identity.events]
                                    if res.identity is not None else []),
            })
            if overlay and view.full is not None and (best is None or res.n_detected > best[1].n_detected):
                best = (view.sample.frame_id, res, view.full)
    run.add_artefact(obs_path, "predictions")
    run.add_artefact(ev_path, "log")
    end_counters = landmarker.counters.to_dict()
    end_ident = landmarker.identity.counters.to_dict()
    ident_delta = {k: end_ident[k] - start_ident[k] for k in end_ident}
    n_det_frames = ident_delta["frames_with_detections"]

    proc_all = [r["processing_s"] for r in rows]
    proc_warm = [r["processing_s"] for r in rows[warmup:]]
    n = len(rows)
    left = sum(r["left_present"] for r in rows)
    right = sum(r["right_present"] for r in rows)
    both = sum(r["left_present"] and r["right_present"] for r in rows)
    metrics: dict[str, Any] = {
        "n_frames": n,
        "frames_left_present": left,
        "frames_right_present": right,
        "frames_both_present": both,
        "frames_any_present": sum(r["left_present"] or r["right_present"] for r in rows),
        "presence_rate_left": left / n if n else None,
        "presence_rate_right": right / n if n else None,
        "presence_rate_both": both / n if n else None,
        "n_detected_histogram": dict(sorted(n_hist.items())),
        "label_collisions": end_counters["label_collisions"] - start_counters["label_collisions"],
        "unknown_labels": end_counters["unknown_labels"] - start_counters["unknown_labels"],
        "timestamp_bumps": end_counters["timestamp_bumps"] - start_counters["timestamp_bumps"],
        "visibility_available": (end_counters["visibility_frames"] - start_counters["visibility_frames"]) > 0,
        "schema_errors": schema_errors,
        "schema_valid_all": schema_errors == 0,
        "identity": {
            "mode": str(landmarker.settings.identity.mode),
            "frames_with_detections": ident_delta["frames_with_detections"],
            "assignments": ident_delta["assigned"],
            "unassigned_detections": ident_delta["unassigned"],
            "ambiguous_frames": ambiguous_frames,
            "label_overrides": ident_delta["label_overrides"],
            "continuity_overrides": ident_delta["continuity_overrides"],
            "identity_jumps": ident_delta["identity_jumps"],
            # rates per frame that had at least one detection (0 detections carry no identity information)
            "rate_label_override_per_detected_frame": _rate(ident_delta["label_overrides"], n_det_frames),
            "rate_identity_jump_per_detected_frame": _rate(ident_delta["identity_jumps"], n_det_frames),
            "rate_ambiguous_per_detected_frame": _rate(ambiguous_frames, n_det_frames),
            "note": "label_overrides = frames x hands where continuity overrode the raw estimator label (the "
                    "raw swap count); continuity_overrides = the label won over the nearest previous wrist "
                    "(expected at a genuine crossing); identity_jumps = assigned detection outside own gate "
                    "but inside the other hand's gate (possible track swap); no deliberate-crossing dev "
                    "capture exists yet (PENDING, no new recordings in Task 03.2).",
        },
        "processing_all_frames": _timing_stats(proc_all),
        "processing_excluding_warmup": {"warmup_frames_excluded": warmup, **_timing_stats(proc_warm)},
        "mean_wrist_x_roi_norm": {k: (float(np.mean(v)) if v else None) for k, v in wrist_x.items()},
        "lighting": cap.meta.get("lighting"),
        "exposure": cap.meta.get("exposure"),
        "roi_px": cap.meta.get("roi_px"),
    }
    run.write_json_artefact(f"per_frame.{cap.name}.json", {"capture": cap.name, "rows": rows})
    if best is not None:
        fid, res, full = best
        img = _draw_overlay(full, cap.roi, res, f"{cap.name} frame {fid}: {res.n_detected} det, "
                                                  f"L={res.left.present} R={res.right.present}")
        p = run.dir / f"overlay.{cap.name}.frame{fid:05d}.png"
        cv2.imwrite(str(p), img)
        run.add_artefact(p, "figure")
        metrics["overlay_frame_id"] = fid
    return metrics


# ----------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    ap.add_argument("--capture", action="append", default=[], help="dev capture name (repeatable)")
    ap.add_argument("--limit", type=int, default=None, help="max frames per capture")
    ap.add_argument("--running-mode", choices=["VIDEO", "IMAGE"], default=None)
    ap.add_argument("--input", choices=["ROI", "FULL"], default=None)
    ap.add_argument("--swap-handedness", action="store_true")
    ap.add_argument("--identity-mode", choices=["RAW", "TEMPORAL"], default=None,
                    help="override hands.identity.mode (RAW = Task 03.1 label-only baseline)")
    ap.add_argument("--warmup", type=int, default=5, help="frames excluded from the second timing block")
    ap.add_argument("--no-overlay", action="store_true")
    ap.add_argument("--synthetic", action="store_true", help="stub backend + in-memory frames (self-test)")
    ap.add_argument("--hardware-id", default="HW-01")
    args = ap.parse_args(argv)

    overrides: dict[str, Any] = {"hands": {}}
    if args.running_mode:
        overrides["hands"]["running_mode"] = args.running_mode
    if args.input:
        overrides["hands"]["input"] = args.input
    if args.swap_handedness:
        overrides["hands"]["swap_handedness"] = True
    if args.identity_mode:
        overrides["hands"]["identity"] = {"mode": args.identity_mode}
    cfg = load_config(args.base_config, args.camera_config, overrides=overrides)
    settings = HandLandmarkerSettings.from_config(cfg.data)

    if args.synthetic:
        names = ["synthetic"]
    else:
        names = args.capture or []
        if not names:
            avail = sorted(p.name for p in DEV_CAPTURES.iterdir()) if DEV_CAPTURES.exists() else []
            print(f"no --capture given; available: {avail}")
            return 2

    slug = "p03-hands-check" + ("-synthetic" if args.synthetic
                                else f"-{settings.running_mode.lower()}-id{settings.identity.mode.lower()}")
    desc = ("Task 03.1/03.2 hand-landmark wrapper + identity check "
            + ("(SYNTHETIC self-test: stub backend, in-memory frames; numbers are not evidence)"
               if args.synthetic else f"on dev captures {names} replayed with recorded t_capture")
            + f"; hands config: running_mode={settings.running_mode}, input={settings.input}, "
              f"num_hands={settings.num_hands}, swap_handedness={settings.swap_handedness}, "
              f"identity.mode={settings.identity.mode}. "
              "Frames with both hands present are REPORTED, not targeted.")
    with RunLog(phase="03", task="03.1", slug=slug, config=cfg, hardware_id=args.hardware_id,
                experiments_dir=args.experiments_dir, description=desc) as run:
        if args.synthetic:
            landmarker = HandLandmarker(settings, backend=StubBackend())
        else:
            landmarker = HandLandmarker(settings)
        print(f"detector_id: {landmarker.detector_id}")
        print(json.dumps(landmarker.describe(), indent=2, default=str))
        cells: dict[str, Any] = {}
        try:
            for name in names:
                if args.synthetic:
                    cap: Any = _SyntheticCapture(Roi.from_rect(cfg["roi"]["px"]))
                    views = _iter_synthetic(cap)
                else:
                    cap = load_dev_capture(name, limit=args.limit)
                    views = iter_views(cap)
                print(f"\n== {name}: {len(cap)} frames, lighting {cap.meta.get('lighting')}, "
                      f"exposure {cap.meta.get('exposure')}, roi {cap.meta.get('roi_px')}")
                m = run_capture(run, landmarker, cap, views, warmup=args.warmup, overlay=not args.no_overlay)
                cells[name] = m
                pa, pw = m["processing_all_frames"], m["processing_excluding_warmup"]
                print(f"  frames {m['n_frames']}: LEFT present {m['frames_left_present']}, RIGHT present "
                      f"{m['frames_right_present']}, BOTH present {m['frames_both_present']} "
                      "(reported, not targeted)")
                print(f"  detections histogram {m['n_detected_histogram']}; label collisions "
                      f"{m['label_collisions']}; unknown labels {m['unknown_labels']}; "
                      f"timestamp bumps {m['timestamp_bumps']}")
                print(f"  schema valid (all records): {m['schema_valid_all']}; visibility available: "
                      f"{m['visibility_available']}")
                print(f"  processing s/frame all: p50 {pa['p50_s']:.4f} p95 {pa['p95_s']:.4f} "
                      f"max {pa['max_s']:.4f}; excl. first {args.warmup}: p50 {pw['p50_s']:.4f} "
                      f"p95 {pw['p95_s']:.4f} max {pw['max_s']:.4f}")
                print(f"  mean wrist x (ROI-norm) per emitted hand_id: {m['mean_wrist_x_roi_norm']}")
                mi = m["identity"]
                print(f"  identity [{mi['mode']}]: detected frames {mi['frames_with_detections']}, "
                      f"label overrides {mi['label_overrides']}, continuity overrides "
                      f"{mi['continuity_overrides']}, identity jumps {mi['identity_jumps']}, "
                      f"ambiguous frames {mi['ambiguous_frames']}")
        finally:
            landmarker.close()
        run.finish({
            "detector": landmarker.describe(),
            "captures": cells,
            "counters_total": landmarker.counters.to_dict(),
            "identity_counters_total": landmarker.identity.counters.to_dict(),
            "synthetic": args.synthetic,
        })
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
