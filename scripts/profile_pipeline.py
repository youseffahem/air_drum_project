"""Profile the production loop including experiment rendering; headless display by default.

Replay PNG decode and live capture wait are measured separately. No camera FPS is inferred
from replay throughput. Allocation/cProfile diagnostics must be run separately from timings.
"""

from __future__ import annotations

import argparse
import cProfile
import functools
import os
import pstats
import time
import tracemalloc
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import cv2
import torch
from _p10 import write_json
from _p16 import CANDIDATES, ResourceSampler, candidate, distribution, evidence

from spacedrums.app import main as app
from spacedrums.app.audio_out import AudioOutput
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.capture import ReplayFrameSource
from spacedrums.commit import PerHandCommitPolicy
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.geometry import GeometryEngine
from spacedrums.hands import HandLandmarker
from spacedrums.models.temporal.adapter import TemporalAnticipator
from spacedrums.models.temporal.data import sha
from spacedrums.prediction import RuleBasedAnticipator
from spacedrums.stick.tip_geom import GeomTipEstimator
from spacedrums.tracking import CausalTracker


class Stages:
    def __init__(self):
        self.rows = []
        self.current = None
        self.decode_s = 0.0
        self.workers = []

    def timed(self, obj, attr, name, stack):
        original = getattr(obj, attr)

        @functools.wraps(original)
        def call(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                if self.current is not None:
                    self.current["stage_s"][name] += time.perf_counter() - start

        stack.enter_context(patch.object(obj, attr, call))

    def install(self, stack):
        perception, step, render, view = (
            app.Perception.__call__,
            DecisionPipeline.step,
            app.render,
            ReplayFrameSource.view,
        )

        def perceive(instance, frame):
            self.start = time.perf_counter()
            self.current = {
                "frame_id": frame.sample.frame_id,
                "t_capture": frame.sample.t_capture,
                "drops": frame.sample.dropped_since_last,
                "decode_s": self.decode_s,
                "stage_s": defaultdict(float),
            }
            observations = perception(instance, frame)
            if hasattr(instance, "worker_stage_s"):
                for name, duration in instance.worker_stage_s.items():
                    self.current["stage_s"][name] += duration
                if not self.workers:
                    self.workers.append(instance.bridge.stats)
            return observations

        def decide(instance, *args, **kwargs):
            result = step(instance, *args, **kwargs)
            if self.current is not None:
                self.current.update(
                    active_arm=str(instance.active_arm),
                    fallback=instance.model_error,
                    predictions=sum(h.model_prediction is not None for h in result.hands.values()),
                    commits=len(result.commits),
                )
            return result

        def draw(*args, **kwargs):
            start = time.perf_counter()
            result = render(*args, **kwargs)
            end = time.perf_counter()
            row = self.current
            row["stage_s"]["overlay"] += end - start
            row["total_s"] = end - self.start
            row["stage_s"]["other_loop"] = max(0.0, row["total_s"] - sum(row["stage_s"].values()))
            self.rows.append(row)
            self.current = None
            return result

        def decode(*args, **kwargs):
            start = time.perf_counter()
            result = view(*args, **kwargs)
            self.decode_s = time.perf_counter() - start
            return result

        for obj, attr, fn in (
            (app.Perception, "__call__", perceive),
            (DecisionPipeline, "step", decide),
            (app, "render", draw),
            (ReplayFrameSource, "view", decode),
        ):
            stack.enter_context(patch.object(obj, attr, fn))
        for obj, attr, name in (
            (HandLandmarker, "detect", "hands"),
            (GeomTipEstimator, "estimate", "stick"),
            (CausalTracker, "update", "tracking"),
            (StreamingFeatures, "update", "features"),
            (StreamingFeatures, "window", "features"),
            (TemporalAnticipator, "predict", "inference"),
            (RuleBasedAnticipator, "predict", "rule"),
            (GeometryEngine, "observe", "geometry"),
            (GeometryEngine, "intersect_prediction", "geometry"),
            (PerHandCommitPolicy, "step", "commit"),
            (AudioOutput, "play", "audio_schedule"),
        ):
            self.timed(obj, attr, name, stack)


def measure(args, session, repeat):
    argv = [
        "--config",
        str(args.config),
        "--source",
        args.source,
        "--overlay-mode",
        "experiment",
        "--session-id",
        f"perf-r{repeat}",
    ]
    if not args.audio:
        argv += ["--no-audio"]
    if session:
        argv += ["--session-dir", str(session)]
    if args.frames:
        argv += ["--max-frames", str(args.frames)]
    if args.seconds:
        argv += ["--max-seconds", str(args.seconds)]
    if args.dashboard:
        argv += ["--dashboard"]
    app_args = app.build_parser().parse_args(argv)
    app_args.opencv_threads = args.opencv_threads
    stages = Stages()
    with ExitStack() as stack:
        stack.enter_context(candidate(args.candidate))
        stages.install(stack)
        # Render the actual overlay. Display driver/window cost is explicitly excluded.
        if not args.display:
            for name in ("namedWindow", "imshow", "destroyAllWindows"):
                stack.enter_context(patch.object(cv2, name, lambda *a, **kw: None))
            stack.enter_context(patch.object(cv2, "waitKey", lambda *a: -1))
            stack.enter_context(patch.object(cv2, "pollKey", lambda: -1))
        with ResourceSampler() as sampler:
            result = app.run(app_args)
    rows = stages.rows
    if not rows or len(rows) != result["frames"]:
        raise ValueError("no complete profiled frames or overlay skipped")
    keys = sorted({k for r in rows for k in r["stage_s"]})
    span = rows[-1]["t_capture"] - rows[0]["t_capture"]
    cpu = sampler.report()
    cpu["perception_workers"] = stages.workers
    child_cpu = sum((w["final_resources"] or {}).get("process_cpu_s", 0) for w in stages.workers)
    cpu["aggregate_cpu_one_core_percent"] = 100 * (cpu["process_cpu_s"] + child_cpu) / cpu["wall_s"]
    return {
        "session": str(session),
        "repeat": repeat,
        "rows": rows,
        "application": result,
        "stages": {k: distribution([r["stage_s"].get(k, 0) for r in rows]) for k in keys},
        "processing": distribution([r["total_s"] for r in rows]),
        "decode": distribution([r["decode_s"] for r in rows]),
        "processing_capacity_fps": len(rows) / sum(r["total_s"] for r in rows),
        "replay_including_decode_capacity_fps": (
            len(rows) / sum(r["total_s"] + r["decode_s"] for r in rows) if args.source == "replay" else None
        ),
        "delivered_processing_fps": (len(rows) - 1) / span if args.source == "live" and span > 0 else None,
        "deadline_misses_30": sum(r["total_s"] > 1 / 30 for r in rows),
        "deadline_misses_60": sum(r["total_s"] > 1 / 60 for r in rows),
        "capture_drops": sum(r["drops"] for r in rows),
        "drop_scope": "historical input drops" if args.source == "replay" else "live queue drops",
        "resources": cpu,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sessions", nargs="*", type=Path, default=[])
    parser.add_argument("--source", choices=("replay", "live"), default="replay")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slug", default="profile")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--frames", type=int)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--opencv-threads", type=int, default=1)
    parser.add_argument("--candidate", choices=CANDIDATES, default="none")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    args = parser.parse_args(argv)
    if (
        args.repeats < 1
        or (args.frames is not None and args.frames < 1)
        or (args.seconds is not None and args.seconds <= 0)
    ):
        parser.error("positive repeats, frames and seconds required")
    if args.source == "replay" and not args.sessions:
        parser.error("replay requires --sessions")
    if args.source == "live" and not (args.frames or args.seconds):
        parser.error("live capture needs a bounded duration/frame count")
    if args.opencv_threads is not None:
        if args.opencv_threads < 1:
            parser.error("positive OpenCV thread count required")
        cv2.setNumThreads(args.opencv_threads)
    with evidence(args.config, args.output, args.slug, "16.1") as (run, cfg):
        inputs = {}
        for session in args.sessions:
            source = ReplayFrameSource(session)
            inputs[str(session)] = {
                "frames": sha(source.dir / "frames.jsonl"),
                "images": {s.image_ref.path: sha(source.dir / s.image_ref.path) for s in source},
            }
        write_json(run.dir / "input-hashes.json", inputs)
        if cfg["stick"]["method_id"] != "GEOM":
            raise ValueError("stage instrumentation currently supports the selected GEOM estimator")
        profiler = cProfile.Profile() if args.diagnostics else None
        if profiler:
            tracemalloc.start(10)
            profiler.enable()
        runs = []
        try:
            for repeat in range(args.repeats):
                for session in args.sessions if args.source == "replay" else [None]:
                    result = measure(args, session, repeat)
                    runs.append(result)
                    write_json(run.dir / f"sample-{len(runs):02d}.json", result)
                    print(f"sample {len(runs)}: p95={result['processing']['p95_ms']:.3f} ms", flush=True)
        finally:
            if profiler:
                profiler.disable()
                snapshot = tracemalloc.take_snapshot()
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                write_json(
                    run.dir / "allocations.json",
                    {
                        "current_bytes": current,
                        "peak_bytes": peak,
                        "retained_allocation_sites": [str(s) for s in snapshot.statistics("lineno")[:40]],
                        "limitation": "Python retained allocations; native allocations excluded",
                    },
                )
                profiler.dump_stats(str(run.dir / "profile.pstats"))
                with (run.dir / "hotspots.txt").open("w", encoding="utf-8") as stream:
                    pstats.Stats(profiler, stream=stream).sort_stats("cumtime").print_stats(70)
        rows = [row for result in runs for row in result["rows"]]
        keys = sorted({k for row in rows for k in row["stage_s"]})
        report = {
            "kind": "allocation/cProfile diagnostic (timings perturbed)" if profiler else "wall-time profile",
            "evidence": "DEVELOPMENT dirty-tree diagnostic" if run.record["git_dirty"] else "MEASURED",
            "source": args.source,
            "candidate": args.candidate,
            "frames": len(rows),
            "runs": len(runs),
            "command_settings": vars(args),
            "threads": {
                "opencv": cv2.getNumThreads(),
                "torch": torch.get_num_threads(),
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
                "mediapipe": "task default",
            },
            "processing": distribution([r["total_s"] for r in rows]),
            "stages": {k: distribution([r["stage_s"].get(k, 0) for r in rows]) for k in keys},
            "audio_device_enabled": args.audio,
            "display_included": args.display,
            "processing_scope": (
                "perception through experiment overlay; includes dashboard publication if enabled; "
                "excludes decode/capture wait and display"
            ),
            "native_60fps_claim": False,
        }
        report["command_settings"] = {
            k: str(v) if isinstance(v, Path) else [str(p) for p in v] if isinstance(v, list) else v
            for k, v in vars(args).items()
        }
        write_json(run.dir / "profile.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
