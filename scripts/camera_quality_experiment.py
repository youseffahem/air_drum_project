"""Developer-only camera/perception audit. Never starts decisions or audio.

Default: measure the unchanged production camera profile first. Explicit
--profiles selects a small exposure comparison; no configuration is written.
Representative raw/diagnostic frames and measurements stay in --output.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np

from spacedrums.app.main import Perception
from spacedrums.app.play import distribution, play_config
from spacedrums.capture import CaptureSettings, LiveFrameSource, OpenCvCamera, Roi
from spacedrums.timing import now
from spacedrums.ui.canvas import Canvas
from spacedrums.ui.developer_demo import draw_status
from spacedrums.ui.preview import mirror_preview

PROPERTIES = (
    "EXPOSURE", "AUTO_EXPOSURE", "GAIN", "BRIGHTNESS", "CONTRAST", "SATURATION",
    "SHARPNESS", "HUE", "GAMMA", "WHITE_BALANCE_BLUE_U", "WHITE_BALANCE_RED_V",
    "WB_TEMPERATURE", "AUTO_WB", "AUTOFOCUS", "FOCUS", "BACKLIGHT", "ZOOM",
    "PAN", "TILT", "IRIS", "FRAME_WIDTH", "FRAME_HEIGHT", "FPS", "FOURCC",
    "FORMAT", "MODE", "CONVERT_RGB", "BUFFERSIZE", "CODEC_PIXEL_FORMAT",
)


def properties(camera):
    out = {}
    for name in PROPERTIES:
        try:
            value = camera.get_prop("CAP_PROP_" + name)
            out[name] = value if value is not None and math.isfinite(value) else None
        except (AttributeError, cv2.error):
            out[name] = None
    return out


class AuditCamera(OpenCvCamera):
    def __init__(self):
        super().__init__()
        self.before_exposure = None
        self.exposure_calls = []

    def apply_exposure(self, mode, value):
        if self.before_exposure is None:
            self.before_exposure = properties(self)
        result = super().apply_exposure(mode, value)
        self.exposure_calls.append(result)
        return result


def analysis_record(analysis):
    if analysis is None:
        return None
    segment = analysis.segment
    return {
        "search_polygon_px": analysis.region.polygon_px.tolist() if analysis.region else None,
        "grip_px": analysis.grip_px,
        "prior_direction_px": analysis.prior_dir_px,
        "notes": list(analysis.notes),
        "candidate_pixels": len(segment.candidate_px) if segment else 0,
        "edge_pixels": segment.n_edge_px if segment else 0,
        "kept_components": segment.n_kept if segment else 0,
        "components": [asdict(c) for c in segment.components] if segment else [],
        "axis": asdict(analysis.axis) if analysis.axis else None,
    }


def diagnostic_frame(view, observations, evidence, analyses, profile, exposure, fps):
    img = mirror_preview(view.full)
    roi = Roi.from_rect(view.sample.roi_px)
    scene = Canvas.for_display(img, True).roi(roi)
    lines = [f"CAM AUDIT {profile} | EXP {exposure} | FPS {fps:.1f}"]
    for hand, e in evidence.items():
        label = "TIP OK" if e.kind == "MEASURED" else "NO MEASURED TIP"
        lines.append(f"{str(hand)[0]}: {label} | {e.reason}")
    draw_status(img, lines)
    for hand, (obs, _) in observations.items():
        if obs.present:
            pts = [tuple(np.rint(np.array(p[:2]) * [roi.w, roi.h]).astype(int))
                   for p in obs.landmarks]
            for chain in ((0, 1, 2, 3, 4), (0, 5, 6, 7, 8), (5, 9, 10, 11, 12),
                          (9, 13, 14, 15, 16), (13, 17, 18, 19, 20), (0, 17)):
                for a, b in zip(chain, chain[1:], strict=False):
                    scene.line(pts[a], pts[b], (255, 170, 70), 1, cv2.LINE_AA)
            for pt in pts:
                scene.circle(pt, 2, (255, 210, 70), -1)
        an = analyses[hand]
        if an and an.region:
            scene.polylines([an.region.polygon_px.astype(np.int32)], True, (220, 130, 210), 1)
        if an and an.axis:
            a, b = an.axis.origin_px, an.axis.support_far_px
            scene.line(tuple(map(round, a)), tuple(map(round, b)), (60, 190, 255), 2)
        e = evidence[hand]
        if e.kind == "MEASURED":
            scene.circle(tuple(np.rint(np.array(e.tip) * [roi.w, roi.h]).astype(int)),
                         7, (60, 255, 100), -1, cv2.LINE_AA)
    return img


def run_profile(cfg, profile, output, seconds, settle, preview):
    settings = CaptureSettings.from_config(cfg)
    if profile != "baseline":
        settings = replace(settings, spec=replace(settings.spec,
            exposure_mode="AUTO" if profile == "auto" else "MANUAL",
            exposure_value=None if profile == "auto" else float(profile)))
    output.mkdir(parents=True, exist_ok=False)
    camera = AuditCamera()
    source = LiveFrameSource(camera, settings)
    perception = None
    rows, reasons = [], Counter()
    report = {"profile": profile, "requested": asdict(settings.spec),
              "participant_evidence": False, "strikes_enabled": False, "audio_enabled": False,
              "opencv_version": cv2.__version__, "error": None}
    best_score, best = -1, None
    try:
        perception = Perception(cfg)
        report["negotiated"] = source.start().to_dict()
        start = now()
        with (output / "observations.jsonl").open("w", encoding="utf-8") as log:
            while now() - start < settle + seconds:
                sample = source.next_frame(timeout=0.2)
                if sample is None:
                    continue
                view = source.view(sample)
                # Clear only debug references so early rejection cannot display a prior hand/frame.
                analyses, observations = {}, {}
                begin = now()
                hands = perception.landmarker.detect(view)
                for obs in (hands.left, hands.right):
                    perception.estimator.last_analysis = None
                    stick = perception.estimator.estimate(view, obs)
                    observations[obs.hand_id] = (obs, stick)
                    analyses[obs.hand_id] = perception.estimator.last_analysis
                latency = (now() - begin) * 1000
                if now() - start < settle:
                    continue
                evidence = perception.estimator.evidence
                gray = cv2.cvtColor(view.roi, cv2.COLOR_BGR2GRAY)
                row = {"frame_id": sample.frame_id, "t_capture": sample.t_capture,
                       "dropped_since_last": sample.dropped_since_last,
                       "luminance": float(gray.mean()),
                       "lower_half_luminance": float(gray[gray.shape[0] // 2:].mean()),
                       "highlight_clipping_fraction": float((gray >= 250).mean()),
                       "perception_ms": latency,
                       "hands": [o.to_dict() for o, _ in observations.values()],
                       "endpoints": [e.to_dict() for e in evidence.values()],
                       "stages": {str(h): analysis_record(an) for h, an in analyses.items()}}
                log.write(json.dumps(row, allow_nan=False) + "\n")
                rows.append(row)
                reasons.update(e.reason for e in evidence.values())
                fps = (len(rows) - 1) / (sample.t_capture - rows[0]["t_capture"]) if len(rows) > 1 else 0
                score = (10 * sum(e.kind == "MEASURED" for e in evidence.values())
                         + sum(o.present for o, _ in observations.values()))
                if score > best_score or preview:
                    diagnostic = diagnostic_frame(view, observations, evidence, analyses, profile,
                                                  camera.get_prop("CAP_PROP_EXPOSURE"), fps)
                    if score > best_score:
                        best_score, best = score, (view.full.copy(), diagnostic, sample.frame_id)
                    if preview:
                        cv2.imshow("SpaceDrums camera audit (no audio)", diagnostic)
                        if cv2.pollKey() & 0xFF in (27, ord("q")):
                            report["stopped_early"] = True
                            break
            report["properties"] = properties(camera)
            if not rows:
                raise RuntimeError("No measured frames after camera settling")
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        source.stop()
        if perception:
            perception.close()
        if preview:
            cv2.destroyAllWindows()
    report.update(before_exposure=camera.before_exposure, exposure_calls=camera.exposure_calls,
                  capture=source.stats().to_dict(), timestamps=source.timestamp_report())
    if rows:
        lum = [r["luminance"] for r in rows]
        hand_frames = sum(h["present"] for r in rows for h in r["hands"])
        tips = sum(e["kind"] == "MEASURED" for r in rows for e in r["endpoints"])
        report.update(
            measured_frames=len(rows), measured_span_s=rows[-1]["t_capture"] - rows[0]["t_capture"],
            mean_roi_luminance=float(np.mean(lum)),
            lower_half_luminance=float(np.mean([r["lower_half_luminance"] for r in rows])),
            highlight_clipping_fraction=float(np.mean([r["highlight_clipping_fraction"] for r in rows])),
            luminance_std=float(np.std(lum)),
            frame_brightness_delta_mean=float(np.mean(np.abs(np.diff(lum)))) if len(lum) > 1 else None,
            effective_fps=(len(rows)-1)/(rows[-1]["t_capture"]-rows[0]["t_capture"]) if len(rows)>1 else None,
            dropped_frames=sum(r["dropped_since_last"] for r in rows[1:]),
            hand_presence_fraction=hand_frames/(2*len(rows)),
            measured_endpoint_fraction=tips/(2*len(rows)),
            endpoint_acceptance_given_hand=tips/hand_frames if hand_frames else None,
            hand_observations=hand_frames, measured_endpoints=tips,
            both_tips_frames=sum(all(e["kind"] == "MEASURED" for e in r["endpoints"]) for r in rows),
            endpoint_reasons=dict(reasons), perception_ms=distribution([r["perception_ms"] for r in rows]),
        )
    if best:
        cv2.imwrite(str(output / "raw.png"), best[0])
        cv2.imwrite(str(output / "diagnostic.png"), best[1])
        report["representative_frame_id"] = best[2]
    report["limitations"] = [
        "No physical strike or audible-path verification. Endpoint presence is not tip accuracy.",
        "Scene/movement not controlled; luminance stability includes subject motion.",
        "Driver property readbacks alone do not prove support; OpenCV 5 unknown sentinel is -1.",
        "No gain/brightness sweep without reliable range/support information.",
        "Capture statistics include settling; per-profile metrics exclude settling.",
    ]
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("profile", "error", "effective_fps", "mean_roi_luminance",
                     "hand_presence_fraction", "endpoint_acceptance_given_hand")}), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--profiles", nargs="+", choices=("baseline", "-5", "-4", "-3", "auto"),
                   default=["baseline"])
    p.add_argument("--seconds", type=float, default=10)
    p.add_argument("--settle", type=float, default=3)
    p.add_argument("--preview", action="store_true")
    args = p.parse_args()
    if args.seconds <= 0 or args.settle < 0:
        p.error("seconds must be positive and settle nonnegative")
    cv2.setNumThreads(1)
    # The audit baseline must stay production, even if the demo exposure differs.
    cfg = play_config()
    args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for i, profile in enumerate(args.profiles):
        report = run_profile(cfg, profile, args.output / f"{i:02d}-{profile}",
                             args.seconds, args.settle, args.preview)
        reports.append(report)
        (args.output / "report.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
        if report["error"] or report.get("stopped_early"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
