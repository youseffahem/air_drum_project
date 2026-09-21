"""Phase 03, Task 03.14: per-stage processing time (hands, stick per method, tracking) on the dev CPU.

Replays a dev capture with frames **pre-decoded into memory** (so PNG decoding is excluded: the live
loop receives frames from memory) and measures, per frame, the wall-clock time of:

* ``hands``    — ``HandLandmarker.detect`` (estimator + identity + grip),
* ``stick``    — ``TipEstimator.estimate`` for both hands, per method (GEOM, AXIS_REFINED, MARKER),
* ``tracking`` — ``CausalTracker.update`` for both hands (GEOM observations),

with ``timing.now()`` deltas (durations, never stored in a record). Reports p50 / p95 / max per stage
and the sum of the p50s / p95s against the requested frame period (1 / requested_fps, arithmetic).
Thread settings are recorded in the run's environment block (``cv2.getNumThreads``). Nothing here
is a latency-reduction claim (integrity I-6): it is the ``hands`` / ``stick`` / ``tracking`` slot of
architecture.md section 8 for this configuration.

Usage:
    python scripts/measure_stage_latency.py --capture swing-L2-exp-5
    python scripts/measure_stage_latency.py --synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _devcapture import iter_views, load_dev_capture  # noqa: E402
from _runlog import ROOT, RunLog  # noqa: E402
from benchmark_tip_methods import _SynthCap  # noqa: E402
from hands_landmark_check import StubBackend, _iter_synthetic  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.capture import Roi  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import HandId, ResetReason, TipMethod  # noqa: E402
from spacedrums.hands import HandLandmarker, HandLandmarkerSettings  # noqa: E402
from spacedrums.stick import StickSettings, make_tip_estimator  # noqa: E402
from spacedrums.tracking import CausalTracker, TrackerSettings  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"
METHODS = [TipMethod.GEOM, TipMethod.AXIS_REFINED, TipMethod.MARKER]
HANDS = (HandId.LEFT, HandId.RIGHT)


def _stats(v: list[float]) -> dict[str, Any]:
    if not v:
        return {"n": 0}
    a = np.array(v)
    return {"n": len(v), "p50_s": float(np.percentile(a, 50)), "p95_s": float(np.percentile(a, 95)),
            "max_s": float(a.max()), "mean_s": float(a.mean())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--experiments-dir", type=Path, default=None)
    ap.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    ap.add_argument("--capture", default="swing-L2-exp-5")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--warmup", type=int, default=5, help="frames excluded from the statistics")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--hardware-id", default="HW-01")
    args = ap.parse_args(argv)

    cfg = load_config(args.base_config, args.camera_config)
    period_s = 1.0 / float(cfg["camera_profile"]["requested_fps"])
    slug = "p03-stage-latency" + ("-synthetic" if args.synthetic else "")
    desc = ("Task 03.14 per-stage processing time (hands, stick per method, tracking) "
            + ("(SYNTHETIC self-test: stub hands; numbers are not evidence)" if args.synthetic
               else f"on dev capture {args.capture} replayed from memory (PNG decoding excluded)")
            + f"; frame period = 1 / requested_fps = {period_s:.4f} s (arithmetic, not a measurement).")
    with RunLog(phase="03", task="03.14", slug=slug, config=cfg, hardware_id=args.hardware_id,
                experiments_dir=args.experiments_dir, description=desc) as run:
        hs = HandLandmarkerSettings.from_config(cfg.data)
        landmarker = HandLandmarker(hs, backend=StubBackend()) if args.synthetic else HandLandmarker(hs)
        stick_settings = StickSettings.from_config(cfg.data)
        estimators = {m: make_tip_estimator(m, stick_settings) for m in METHODS}
        ts = TrackerSettings.from_config(cfg.data)
        trackers = {h: CausalTracker(h, ts) for h in HANDS}
        for t in trackers.values():
            t.reset(ResetReason.SESSION_START)
        if args.synthetic:
            cap: Any = _SynthCap(Roi.from_rect(cfg["roi"]["px"]), n=20)
            views = list(_iter_synthetic(cap))
        else:
            cap = load_dev_capture(args.capture, limit=args.limit)
            views = list(iter_views(cap))  # pre-decoded: the loop below measures processing only
        times: dict[str, list[float]] = {"hands": [], "tracking": [], "total_geom_pipeline": []}
        for m in METHODS:
            times[f"stick_{m.value}"] = []
        try:
            for k, view in enumerate(views):
                t0 = timing.now()
                res = landmarker.detect(view)
                t1 = timing.now()
                geom_obs = {}
                for m in METHODS:
                    ta = timing.now()
                    for h in HANDS:
                        obs = res.left if h is HandId.LEFT else res.right
                        so = estimators[m].estimate(view, obs)
                        if m is TipMethod.GEOM:
                            geom_obs[h] = (obs, so)
                    tb = timing.now()
                    if k >= args.warmup:
                        times[f"stick_{m.value}"].append(tb - ta)
                t2 = timing.now()
                for h in HANDS:
                    obs, so = geom_obs[h]
                    trackers[h].update(obs, so, view.sample.t_capture)
                t3 = timing.now()
                if k >= args.warmup:
                    times["hands"].append(t1 - t0)
                    times["tracking"].append(t3 - t2)
                    # the live pipeline runs ONE method; the GEOM path is the primary candidate
                    times["total_geom_pipeline"].append((t1 - t0) + (t3 - t2) + times["stick_GEOM"][-1])
        finally:
            landmarker.close()
        stats = {k: _stats(v) for k, v in times.items()}
        sum_p50 = sum(stats[k]["p50_s"] for k in ("hands", "stick_GEOM", "tracking") if stats[k]["n"])
        sum_p95 = sum(stats[k]["p95_s"] for k in ("hands", "stick_GEOM", "tracking") if stats[k]["n"])
        metrics = {
            "capture": args.capture if not args.synthetic else "synthetic",
            "frames_measured": len(times["hands"]), "warmup_excluded": args.warmup,
            "stages": stats,
            "sum_of_stage_p50_s": sum_p50, "sum_of_stage_p95_s": sum_p95,
            "frame_period_s_arithmetic": period_s,
            "sum_p50_over_frame_period": sum_p50 / period_s if period_s else None,
            "terms": "hands + stick_GEOM (both hands) + tracking (both hands); PNG decoding excluded; "
                     "capture hand-over excluded (Phase 02 measured it separately)",
            "synthetic": args.synthetic,
        }
        print("| stage | n | p50 ms | p95 ms | max ms |")
        print("|---|---|---|---|---|")
        for k, v in stats.items():
            if v["n"]:
                print(f"| {k} | {v['n']} | {1000 * v['p50_s']:.2f} | {1000 * v['p95_s']:.2f} | "
                      f"{1000 * v['max_s']:.2f} |")
        print(f"sum of p50 (hands + stick_GEOM + tracking) = {1000 * sum_p50:.1f} ms vs frame period "
              f"{1000 * period_s:.1f} ms (ratio {sum_p50 / period_s:.2f}); "
              f"sum of p95 = {1000 * sum_p95:.1f} ms")
        run.write_json_artefact("stage_latency.json", {"per_frame_s": times, "stats": stats})
        run.finish(metrics)
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
