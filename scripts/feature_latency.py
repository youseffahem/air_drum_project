"""Development CPU latency on explicitly SYNTHETIC input, with real perf-counter timings."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from time import perf_counter_ns

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from _runlog import RunLog  # noqa: E402

from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import HandObservation, StickObservation, TrackState  # noqa: E402
from spacedrums.features.groups import GROUPS  # noqa: E402
from spacedrums.features.schema import FeatureSchema  # noqa: E402
from spacedrums.features.streaming import StreamingFeatures  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--synthetic", action="store_true", required=True)
    ap.add_argument("--iterations", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments/phase-08")
    args = ap.parse_args(argv)
    if args.iterations < 20 or args.warmup < 1:
        ap.error("at least 20 measured iterations and one warmup required")
    config = load_config(
        ROOT / "configs/prototype.candidate.yaml",
        ROOT / "configs/zones/v1-7.candidate.yaml",
        ROOT / "configs/features/fs-v1.candidate.yaml",
    )
    track = TrackState(
        0,
        100.0,
        "RIGHT",
        "VALID",
        "synthetic-feature-latency",
        "GEOM",
        (0.4, 0.4),
        (0.1, 1.0),
        (0.2, -0.3),
        0.3,
        0.1,
        0.9,
        0,
        100.0,
        None,
        None,
    )
    landmarks = tuple((0.3 + i * 0.005, 0.4 + i * 0.006) for i in range(21))
    hand = HandObservation(0, 100.0, "RIGHT", True, "synthetic", landmarks, None, 0.95, (0.3, 0.4, 0.1, 0.15))
    stick = StickObservation(
        0, 100.0, "RIGHT", True, "GEOM", (0.3, 0.4), (0.0, 1.0), (0.4, 0.4), 0.9, 0.8, 0.2
    )
    full = FeatureSchema(config["zones"], groups=GROUPS)
    # Largest proper group ablation: drop the smallest group (TIME, two fields).
    largest_subset = FeatureSchema(config["zones"], groups=tuple(g for g in GROUPS if g != "TIME"))
    default = FeatureSchema(config["zones"])
    with RunLog(
        phase="08",
        task="08.9",
        slug="p08-feature-latency",
        config=config,
        description="CPU streaming feature cost; SYNTHETIC records, seven zones. "
        "No dataset, camera, participant or end-to-end latency measurement.",
        experiments_dir=args.experiments_dir,
    ) as run:
        metrics = {
            "input_evidence": "SYNTHETIC",
            "timing_evidence": "HARDWARE MEASUREMENT (development)",
            "iterations": args.iterations,
            "warmup": args.warmup,
            "variants": {},
        }
        for name, schema in (
            ("full_with_jerk", full),
            ("largest_group_ablation_without_time", largest_subset),
            ("default_without_jerk", default),
        ):
            stream = StreamingFeatures(schema, history_n=32)
            timings = []
            for i in range(args.warmup + args.iterations):
                t = 100.0 + i / 30
                tr = replace(
                    track,
                    frame_id=i,
                    t_capture=t,
                    last_valid_t=t,
                    tip_filtered=(0.4 + 0.08 * np.sin(i * 0.08), 0.4 + 0.12 * np.cos(i * 0.08)),
                )
                ho, so = replace(hand, frame_id=i, t_capture=t), replace(stick, frame_id=i, t_capture=t)
                start = perf_counter_ns()
                stream.update(tr, hand=ho, stick=so)
                duration = (perf_counter_ns() - start) / 1e6
                if i >= args.warmup:
                    timings.append(duration)
            metrics["variants"][name] = {
                "dimension": schema.dimension,
                "groups": list(schema.groups),
                "p50_ms": float(np.percentile(timings, 50)),
                "p95_ms": float(np.percentile(timings, 95)),
                "max_ms": max(timings),
                "schema_hash": schema.fingerprint,
            }
            run.write_json_artefact(name + ".json", {"schema": schema.descriptor(), "timings_ms": timings})
        run.finish(
            metrics,
            notes="perf_counter_ns around StreamingFeatures.update only; input construction, "
            "disk I/O and window normalization excluded. Real CPU timings on synthetic motion. "
            "No accuracy or reduced end-to-end latency claim; dirty-tree runs are development only.",
        )
        print(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
