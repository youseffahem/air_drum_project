"""Replay perception candidates on developer frames; accuracy needs independent labels.

All timings are measured compute costs, never native-camera FPS. Hand detection
is run once per candidate; no future frames or saved future tracking are used.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from spacedrums.app.main import Perception
from spacedrums.capture import ReplayFrameSource
from spacedrums.config import load_config
from spacedrums.contracts import FrameView, HandId, HandObservation
from spacedrums.hands import HandLandmarker, HandLandmarkerSettings
from spacedrums.hands.body import BodyLandmarker
from spacedrums.hands.coords import DetectorInput
from spacedrums.stick import StickSettings, make_tip_estimator
from spacedrums.stick.visible import VisibleEndpointEstimator, VisibleSettings
from spacedrums.timing import now


def stats(values):
    return dict(zip(("p50", "p95", "max"), map(float, np.percentile(values, [50, 95, 100])), strict=True))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit", type=int, default=325)
    p.add_argument("--start-frame", type=int, default=0)
    p.add_argument("--compare-full-roi", action="store_true")
    p.add_argument("--saved-hands", action="store_true")
    a = p.parse_args()
    cv2.setNumThreads(1)
    cfg = load_config("configs/prototype.candidate.yaml").data
    source = ReplayFrameSource(a.session)
    samples = [s for s in source.samples if s.frame_id >= a.start_frame][: a.limit]
    views = [source.view(s) for s in samples]
    out = {
        "provenance": "DEVELOPER_REPLAY",
        "source": str(a.session),
        "frames": len(views),
        "participant_evidence": False,
        "quality_ground_truth": None,
        "false_hit_rate": None,
        "missed_hit_rate": None,
        "candidates": {},
    }
    try:
        out["gpu"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu", "--format=csv"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        out["gpu"] = None
    try:
        gpu = HandLandmarker(replace(HandLandmarkerSettings.from_config(cfg), delegate="GPU"))
        gpu.close()
        out["gpu_delegate"] = "INITIALIZED"
    except Exception as exc:
        out["gpu_delegate"] = f"UNAVAILABLE: {type(exc).__name__}: {exc}"
    if a.saved_hands:
        if (a.session / "observations.jsonl").exists():
            rows = [
                h
                for line in (a.session / "observations.jsonl").read_text().splitlines()
                for h in json.loads(line)["hands"]
            ]
        else:
            rows = [
                json.loads(line)
                for line in (a.session / "records/HandObservation.jsonl").read_text().splitlines()
            ]
        lookup = {
            (r["frame_id"], r["hand_id"]): HandObservation.from_dict(r) for r in rows if "frame_id" in r
        }
        settings = StickSettings.from_config(cfg)
        for name, est in (
            ("legacy_GEOM", make_tip_estimator("GEOM", settings)),
            ("visible_paired_edges", VisibleEndpointEstimator(settings, mode="paired")),
            ("visible_fixed_search", VisibleEndpointEstimator(settings, VisibleSettings(max_search_spans=7))),
            ("visible_connected_support", VisibleEndpointEstimator(settings)),
        ):
            costs, count, reasons = [], Counter(), Counter()
            for v in views:
                t = now()
                for h in HandId:
                    rec = est.estimate(v, lookup[(v.sample.frame_id, str(h))])
                    count["hand_frames"] += 1
                    count["present"] += int(rec.present)
                    count["confidence_ge_065"] += int(rec.tip_confidence >= 0.65)
                    if hasattr(est, "evidence"):
                        reasons[est.evidence[h].reason] += 1
                costs.append((now() - t) * 1000)
            out["candidates"][name] = {
                "both_sticks_compute_ms": stats(costs),
                "counts": dict(count),
                "reasons": dict(reasons),
                "hands_source": "SAVED_CURRENT_FRAME",
            }
    else:
        candidates = [
            ("legacy_ROI", False, False, False),
            ("visible_ROI", False, True, False),
            ("visible_FULL", True, True, False),
        ]
        if a.compare_full_roi:
            candidates.append(("visible_full_camera_roi", True, True, True))
        for name, full, product, recrop in candidates:
            candidate = load_config("configs/prototype.candidate.yaml").data
            candidate["hands"]["input"] = str(DetectorInput.FULL if full else DetectorInput.ROI)
            candidate["product"] = {"enabled": product}
            est = Perception(candidate)
            costs, hands_ms, counts = [], [], Counter()
            wall, cpu = now(), time.process_time()
            previous = {h: False for h in HandId}
            for v in views:
                if recrop:
                    fw, fh = v.sample.frame_size_px
                    v = FrameView(sample=replace(v.sample, roi_px=(0, 0, fw, fh)), roi=v.full, full=v.full)
                t = now()
                recs = est(v)
                costs.append((now() - t) * 1000)
                hands_ms.append(est.last_hands.processing_s * 1000)
                counts["both_hands"] += int(all(o.present for o, s in recs.values()))
                counts["both_sticks"] += int(all(s.present for o, s in recs.values()))
                for h, (hand, stick) in recs.items():
                    counts["hand_present"] += int(hand.present)
                    valid = stick.present and stick.tip_confidence >= 0.65
                    counts["tip_confidence_ge_065"] += int(valid)
                    counts["tip_losses"] += int(previous[h] and not valid)
                    previous[h] = valid
            elapsed = now() - wall
            cpu_s = time.process_time() - cpu
            out["candidates"][name] = {
                "perception_ms": stats(costs),
                "hand_inference_ms": stats(hands_ms),
                "counts": dict(counts),
                "cpu_core_percent": cpu_s / elapsed * 100,
                "compute_throughput_fps": len(views) / elapsed,
                "endpoint_counters": dict(est.estimator.counters),
                "roi": "FULL_CAMERA" if recrop else "RECORDED",
            }
            est.close()
        pose = BodyLandmarker("mediapipe-pose-landmarker-full-float16-v1")
        pose_ms, present = [], 0
        for v in views[::6]:
            body = pose.detect(v)
            present += body is not None
            pose_ms.append(pose.processing_s * 1000)
        pose.close()
        out["pose"] = {"samples": len(pose_ms), "reference_present": present, "inference_ms": stats(pose_ms)}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
