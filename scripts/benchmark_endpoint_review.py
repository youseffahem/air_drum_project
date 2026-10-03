"""Endpoint-only CPU benchmark on cached images/hands; not camera or app FPS."""

import argparse
import json
import platform
import time
from pathlib import Path

import cv2
import numpy as np
from _endpoint_candidate import ProfileEndpointCandidate
from review_developer_endpoints import load_capture, quantiles, view_for

from spacedrums.contracts import HandObservation
from spacedrums.stick.estimator import StickSettings
from spacedrums.stick.visible import VisibleEndpointEstimator, VisibleSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("experiments/developer-endpoint-check-20261004-01")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("experiments/developer-endpoint-offline-20261004-01")
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    report, rows, images = load_capture(args.source)
    inputs = [
        (view_for(r, im, report["config"]["roi"]["px"]), [HandObservation.from_dict(h) for h in r["hands"]])
        for r, im in zip(rows, images, strict=True)
    ]
    settings = StickSettings.from_config(report["config"])
    names = ("support", "paired", "profile_single", "profile_temporal")
    result = {
        "scope": "two hand slots/frame, saved current hands, image decode and JSON excluded; CPU only",
        "platform": platform.platform(),
        "processor": platform.processor(),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "opencv_threads": cv2.getNumThreads(),
        "frames": len(rows),
        "repeats": args.repeats,
        "runs": {n: [] for n in names},
    }
    for repeat in range(args.repeats):
        for name in names[repeat:] + names[:repeat]:

            def make(name=name):
                if name.startswith("profile"):
                    return ProfileEndpointCandidate(settings.grip, temporal=name == "profile_temporal")
                return VisibleEndpointEstimator(
                    settings, VisibleSettings(**report["config"]["product"]["endpoint"]), mode=name
                )

            def process(est, v, hs, name=name):
                if name.startswith("profile"):
                    est.process(v, hs)
                else:
                    for h in hs:
                        est.estimate(v, h)

            est = make()
            for v, hs in inputs[100:130]:
                process(est, v, hs)
            est = make()
            costs = []
            cpu = time.process_time()
            begin = time.perf_counter()
            for v, hs in inputs:
                start = time.perf_counter()
                process(est, v, hs)
                costs.append((time.perf_counter() - start) * 1000)
            wall = time.perf_counter() - begin
            cpu = time.process_time() - cpu
            result["runs"][name].append(
                {
                    "compute_ms": quantiles(costs),
                    "mean_ms": float(np.mean(costs)),
                    "wall_s": wall,
                    "process_cpu_s": cpu,
                    "per_frame_ms": costs,
                }
            )
            print(
                f"repeat {repeat + 1} {name}: {np.median(costs):.2f}ms p50 / "
                f"{np.percentile(costs, 95):.2f}ms p95",
                flush=True,
            )
            (args.output / "benchmark.json").write_text(json.dumps(result, indent=2))
    result["summary"] = {
        name: {
            "pooled_ms": quantiles([t for run in runs for t in run["per_frame_ms"]]),
            "mean_ms": float(np.mean([t for run in runs for t in run["per_frame_ms"]])),
            "median_run_p50_ms": float(np.median([run["compute_ms"]["p50"] for run in runs])),
        }
        for name, runs in result["runs"].items()
    }
    # Paired subtraction on the same original frame; a counterfactual budget, not measured app FPS.
    result["estimated_perception_budget"] = {}
    base = np.median([r["per_frame_ms"] for r in result["runs"]["support"]], axis=0)
    for name in names:
        candidate = np.median([r["per_frame_ms"] for r in result["runs"][name]], axis=0)
        estimated = np.array([r["perception_ms"] for r in rows]) - base + candidate
        result["estimated_perception_budget"][name] = {
            "status": "INFERRED, different run from original hand detector",
            "ms": quantiles(estimated.tolist()),
            "fraction_under_33_33_ms": float(np.mean(estimated <= 1000 / 30)),
        }
    (args.output / "benchmark.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
