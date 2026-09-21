"""Phase 02, Task 02.4 (+02.2): native FPS, frame-interval jitter, drops/stalls/duplicates,
timestamp-mapping residuals and capture-thread CPU usage per requested mode.

For every cell (backend x resolution x requested FPS x exposure) x repeat, the script runs
``LiveFrameSource`` for ``--duration`` seconds and reports what the camera DELIVERED:

* delivered FPS = (N - 1) / (t_last - t_first) over delivered *unique* frames (integrity I-5:
  never the requested rate, never counting byte-identical padded frames);
* interval mean/std/p1/p50/p99/max, histogram, gaps (> 1.5x nominal) and stalls (> stall_factor
  x nominal), queue drops, duplicates refused;
* per-frame timestamp source counts and the driver-timestamp mapper residuals (Task 02.2);
* hand-over lag ``t_frame_available - t_capture`` distribution;
* capture-thread CPU time / wall time.

Output: one experiment-log run directory (``experiments/<run_id>/``) with ``run.json``,
``config.resolved.yaml``, ``stdout.log`` and ``fps_cells.json`` (every cell in full).

Usage (from the repository root, development venv):

    python scripts/measure_fps.py --backend MSMF --modes 640x480@30,640x480@60,1280x720@30,1280x720@60 \
        --exposure MANUAL:-6 --duration 60 --repeats 2
    python scripts/measure_fps.py --synthetic --duration 2     # self-test, no camera

Nothing here interpolates or resamples frames.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import ROOT, RunLog  # noqa: E402

from spacedrums import timing  # noqa: E402
from spacedrums.capture import (  # noqa: E402
    CaptureSettings,
    LiveFrameSource,
    OpenCvCamera,
    SyntheticCamera,
    interval_stats,
)
from spacedrums.capture.backend import CameraOpenSpec  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import TimestampSource  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"


def parse_modes(text: str) -> list[tuple[int, int, float]]:
    out = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        res, fps = item.split("@")
        w, h = res.lower().split("x")
        out.append((int(w), int(h), float(fps)))
    return out


def parse_exposure(text: str) -> tuple[str, float | None]:
    mode, _, value = text.partition(":")
    mode = mode.upper()
    if mode == "AUTO":
        return "AUTO", None
    if mode == "MANUAL" and value:
        return "MANUAL", float(value)
    raise argparse.ArgumentTypeError("exposure must be AUTO or MANUAL:<value>")


def run_cell(
    *,
    camera_factory: Any,
    settings: CaptureSettings,
    duration_s: float,
    nominal_fps: float,
) -> dict[str, Any]:
    src = LiveFrameSource(camera_factory(), settings)
    mode = src.start()
    t_cap: list[float] = []
    t_avail: list[float] = []
    sources: dict[str, int] = {}
    dropped_sum = 0
    t_end = timing.now() + duration_s
    lum_samples: list[float] = []
    while timing.now() < t_end:
        f = src.next_frame(timeout=0.5)
        if f is None:
            if src._queue.closed:  # finite synthetic source exhausted
                break
            continue
        t_cap.append(f.t_capture)
        t_avail.append(f.t_frame_available)
        sources[str(f.timestamp_source)] = sources.get(str(f.timestamp_source), 0) + 1
        dropped_sum += f.dropped_since_last
        if len(t_cap) % 30 == 1:
            lum_samples.append(float(f.image_ref.array.mean()))
    stats = src.stats()
    report = src.timestamp_report()
    exposure_report = src.exposure_report
    src.stop()
    cell: dict[str, Any] = {
        "negotiated": mode.to_dict(),
        "exposure_applied": exposure_report,
        "capture_stats": stats.to_dict(),
        "timestamp_report": report,
        "timestamp_sources_delivered": sources,
        "dropped_since_last_sum": dropped_sum,
        "mean_luminance_samples": {"n": len(lum_samples),
                                   "mean": float(np.mean(lum_samples)) if lum_samples else None},
    }
    if len(t_cap) >= 2:
        ist = interval_stats(t_cap, 1.0 / nominal_fps, stall_factor=settings.stall_factor)
        lag = np.array(t_avail) - np.array(t_cap)
        cell["interval_stats"] = ist.to_dict()
        cell["delivered_fps"] = ist.fps
        cell["handover_lag_s"] = {
            "p50": float(np.percentile(lag, 50)), "p95": float(np.percentile(lag, 95)),
            "max": float(lag.max()), "min": float(lag.min()),
        }
    else:
        cell["interval_stats"] = None
        cell["delivered_fps"] = None
    return cell


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-config", type=Path, default=DEFAULT_BASE)
    p.add_argument("--camera-config", type=Path, default=DEFAULT_CAMERA)
    p.add_argument("--backend", default=None, help="MSMF | DSHOW (default: camera config)")
    p.add_argument("--index", type=int, default=None)
    p.add_argument("--modes", default="640x480@30", help="comma list WxH@fps")
    p.add_argument("--pixel-format", default=None, help="FOURCC to request (e.g. MJPG)")
    p.add_argument("--exposure", type=parse_exposure, default=None, help="AUTO or MANUAL:<value>")
    p.add_argument("--timestamp-source", choices=["DRIVER_MAPPED", "GRAB_RETURN"], default=None)
    p.add_argument("--duration", type=float, default=60.0, help="seconds per cell (candidate >= 60)")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--queue", type=int, default=None, help="queue max_frames override")
    p.add_argument("--slug", default=None)
    p.add_argument("--hardware-id", default="HW-01")
    p.add_argument("--experiments-dir", type=Path, default=None)
    p.add_argument("--synthetic", action="store_true", help="self-test with SyntheticCamera")
    p.add_argument("--no-dedupe", action="store_true", help="count byte-identical frames (diagnostic only)")
    args = p.parse_args(argv)

    overrides: dict[str, Any] = {"camera_profile": {"device": {}, "exposure": {}}}
    if args.backend:
        overrides["camera_profile"]["device"]["backend"] = args.backend.upper()
    if args.index is not None:
        overrides["camera_profile"]["device"]["index"] = args.index
    if args.pixel_format:
        overrides["camera_profile"]["pixel_format"] = args.pixel_format.upper()
    if args.exposure:
        overrides["camera_profile"]["exposure"] = {"mode": args.exposure[0], "value": args.exposure[1]}
    if args.timestamp_source:
        overrides["camera_profile"]["timestamp_source"] = args.timestamp_source
    if args.queue:
        overrides["camera_profile"]["queue"] = {"max_frames": args.queue}
    cfg = load_config(args.base_config, args.camera_config, overrides=overrides)
    cam = cfg["camera_profile"]
    modes = parse_modes(args.modes)
    slug = args.slug or (f"p02-fps-{(cam['device']['backend'] or 'any').lower()}"
                         + ("-synthetic" if args.synthetic else ""))
    description = (
        f"Task 02.4 native FPS / jitter / drops per requested mode on {args.hardware_id}: "
        f"backend {cam['device']['backend']}, modes {args.modes}, exposure {cam['exposure']}, "
        f"{args.duration:.0f} s x {args.repeats} repeat(s); delivered FPS from t_capture of unique frames."
    )
    with RunLog(phase="02", task="02.4", slug=slug, description=description, config=cfg,
                hardware_id=args.hardware_id, experiments_dir=args.experiments_dir) as run:
        cells = []
        metrics: dict[str, Any] = {"cells": {}}
        for (w, h, fps) in modes:
            for rep in range(args.repeats):
                spec = CameraOpenSpec(
                    index=cam["device"]["index"] or 0, backend=cam["device"]["backend"],
                    width=w, height=h, fps=fps, pixel_format=cam.get("pixel_format"),
                    exposure_mode=cam["exposure"]["mode"], exposure_value=cam["exposure"]["value"],
                )
                settings = CaptureSettings(
                    camera_profile_id=cam["profile_id"], spec=spec, roi=None,
                    timestamp_source=TimestampSource(cam["timestamp_source"]),
                    queue_max_frames=cam["queue"]["max_frames"],
                    stall_factor=cam["queue"]["stall_factor"], nominal_fps=fps,
                    dedupe=not args.no_dedupe,
                )
                if args.synthetic:
                    def factory(fps=fps, w=w, h=h):
                        return SyntheticCamera(width=w, height=h, fps=min(fps, 120), paced=True,
                                               duplicate_every=10, drv_offset=1234.5)
                else:
                    factory = OpenCvCamera
                label = f"{w}x{h}@{fps:g}-{cam['exposure']['mode']}-r{rep + 1}"
                print(f"\n=== cell {label}: {args.duration:.0f} s ===")
                cell = run_cell(camera_factory=factory, settings=settings,
                                duration_s=args.duration, nominal_fps=fps)
                cell["label"] = label
                cell["requested"] = {"width": w, "height": h, "fps": fps, "repeat": rep + 1,
                                     "backend": cam["device"]["backend"],
                                     "pixel_format": cam.get("pixel_format"),
                                     "exposure": cam["exposure"], "duration_s": args.duration,
                                     "timestamp_source_policy": cam["timestamp_source"],
                                     "dedupe": not args.no_dedupe}
                cells.append(cell)
                cs = cell["capture_stats"]
                ist = cell["interval_stats"]
                if ist:
                    print(f"delivered FPS {cell['delivered_fps']:.2f} (unique frames {ist['n_frames']}), "
                          f"interval mean {ist['mean_s']*1e3:.2f} ms std {ist['std_s']*1e3:.2f} "
                          f"p1 {ist['p1_s']*1e3:.2f} p50 {ist['p50_s']*1e3:.2f} p99 {ist['p99_s']*1e3:.2f} "
                          f"max {ist['max_s']*1e3:.2f} | gaps {ist['n_gaps']} stalls {ist['n_stalls']}")
                    print(f"queue dropped {cs['dropped']} | duplicates refused {cs['duplicates']} | "
                          f"clamped ts {cs['clamped_timestamps']} | "
                          f"sources {cell['timestamp_sources_delivered']} | "
                          f"handover lag p50 {cell['handover_lag_s']['p50']*1e3:.1f} ms p95 "
                          f"{cell['handover_lag_s']['p95']*1e3:.1f} ms | capture-thread CPU "
                          f"{(cell['timestamp_report']['capture_thread_cpu_fraction'] or 0)*100:.1f} %")
                    dm = cell["timestamp_report"]["driver_mapper"]
                    if dm.get("mode"):
                        print(f"driver mapper {dm['mode']}: b-1 = {dm['ls_slope_minus_1']:.2e}, "
                              f"lag p50 {dm['lag_p50_s']*1e3:.1f} ms p95 {dm['lag_p95_s']*1e3:.1f} ms, "
                              f"LS residual std {dm['ls_residual_std_s']*1e3:.2f} ms")
                    metrics["cells"][label] = {
                        "fps_delivered": cell["delivered_fps"],
                        "interval_std_s": ist["std_s"], "interval_p1_s": ist["p1_s"],
                        "interval_p50_s": ist["p50_s"], "interval_p99_s": ist["p99_s"],
                        "n_frames": ist["n_frames"], "gaps": ist["n_gaps"], "stalls": ist["n_stalls"],
                        "dropped": cs["dropped"], "duplicates": cs["duplicates"],
                        "clamped_timestamps": cs["clamped_timestamps"],
                        "handover_lag_p50_s": cell["handover_lag_s"]["p50"],
                        "capture_thread_cpu_fraction":
                            cell["timestamp_report"]["capture_thread_cpu_fraction"],
                        "negotiated": f"{cell['negotiated']['width']}x{cell['negotiated']['height']} "
                                      f"{cell['negotiated']['fourcc']} "
                                      f"fps_prop={cell['negotiated']['fps_prop']}",
                    }
                else:
                    print("no frames delivered")
                    metrics["cells"][label] = {"fps_delivered": None, "n_frames": 0}
        run.write_json_artefact("fps_cells.json", {"cells": cells, "clock": timing.clock_info()})
        run.finish(metrics)
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
