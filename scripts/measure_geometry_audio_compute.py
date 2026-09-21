"""Profile Phase 04 geometry plus scheduling on labelled synthetic trajectories."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _runlog import RunLog  # noqa: E402

from spacedrums.audio import AudioScheduler  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import CommittedStrike  # noqa: E402
from spacedrums.geometry import GeometryEngine, TrajectoryPoint, ZoneRegistry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--experiments-dir", type=Path, default=ROOT / "experiments")
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    if not args.synthetic:
        parser.error("benchmark input is synthetic; pass --synthetic to acknowledge")
    layout = ROOT / "configs/zones/mvp4.candidate.yaml"
    config = load_config(ROOT / "configs/example.candidate.yaml", layout)
    registry = ZoneRegistry.load(layout)
    engine = GeometryEngine(registry, v_min=0.1, session_id="profile")
    scheduler = AudioScheduler(
        audio_profile_id="synthetic-compute-only", output_latency_measured_s=0.0,
        zone_samples={zone.zone_id: zone.sample_id for zone in registry}, clock=lambda: 1.0,
    )
    trajectory = (TrajectoryPoint(1.0, (0.40, 0.50)), TrajectoryPoint(1.1, (0.40, 0.64)))
    timings = []
    with RunLog(
        phase="04", task="04.8", slug="p04-geometry-schedule-cost",
        description="SYNTHETIC geometry plus scheduling compute profile", config=config,
        experiments_dir=args.experiments_dir,
    ) as run:
        for i in range(args.iterations):
            start = perf_counter()
            candidate = engine.intersect(
                trajectory, source="RULE", frame_id=i, hand_id="RIGHT", t_capture=1.0,
                anticipator_id="synthetic-profile", t_candidate=1.0,
            )
            if candidate is None:
                raise RuntimeError("synthetic profile path did not cross snare")
            committed = CommittedStrike(
                strike_id=f"s{i}", candidate_id=candidate.candidate_id, frame_id=i,
                t_capture=1.0, hand_id="RIGHT", zone_id=candidate.zone_id, source="RULE",
                derivation="GEOMETRY", arm="B", shadow=False, t_commit=1.0,
                t_impact_target=candidate.t_impact_pred or 1.0,
                intensity_proxy=candidate.intensity_proxy, gain=0.5, refractory_until=1.2,
                episode_id=f"e{i}", commit_policy_id="synthetic-harness-only",
            )
            scheduler.schedule(committed)
            timings.append((perf_counter() - start) * 1000)
        ordered = sorted(timings)
        metrics = {
            "input": "SYNTHETIC analytic trajectory", "iterations": len(timings),
            "geometry_plus_schedule_ms_p50": statistics.median(timings),
            "geometry_plus_schedule_ms_p95": ordered[int(0.95 * (len(ordered) - 1))],
            "geometry_plus_schedule_ms_max": max(timings),
            "output_latency_value_used_s": 0.0,
            "output_latency_value_label": "SYNTHETIC COMPUTE-ONLY PLACEHOLDER; not evidence",
        }
        run.write_json_artefact("compute_timings.json", {**metrics, "timings_ms": timings}, "table")
        run.finish(metrics)
        print(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
