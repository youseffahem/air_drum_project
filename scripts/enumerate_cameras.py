"""Phase 02, Task 02.1: enumerate cameras, backends and candidate modes through the capture backend.

Everything this script prints is *inspected / advertised by the driver* (docs/hardware-inventory.md
labelling), never measured: the short unique-frame probe per mode only shows whether a negotiated
mode is plausibly delivered; the delivered rate is measured by scripts/measure_fps.py.

Output: experiments/<run_id>/cameras.json (+ run.json) and a Markdown table on stdout for the
hardware inventory.

Usage:
    python scripts/enumerate_cameras.py [--max-index 3] [--backends MSMF,DSHOW] [--exposure MANUAL:-7]
    python scripts/enumerate_cameras.py --synthetic   # self-test: writes the run without a camera
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _runlog import ROOT, RunLog  # noqa: E402

from spacedrums.capture.device import (  # noqa: E402
    DEFAULT_BACKENDS,
    DEFAULT_MODES,
    available_backends,
    enumerate_devices,
    list_pnp_cameras,
    probe_mode,
)
from spacedrums.config import load_config  # noqa: E402

DEFAULT_BASE = ROOT / "configs" / "example.candidate.yaml"
DEFAULT_CAMERA = ROOT / "configs" / "camera" / "hw01-integrated-webcam.candidate.yaml"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max-index", type=int, default=3)
    p.add_argument("--backends", default=",".join(DEFAULT_BACKENDS))
    p.add_argument("--index", type=int, default=0, help="device index to probe modes on")
    p.add_argument("--exposure", default="MANUAL:-7",
                   help="exposure for the mode probe (manual avoids the low-light frame-rate cap)")
    p.add_argument("--pixel-formats", default="default,MJPG", help="comma list; 'default' = none requested")
    p.add_argument("--hardware-id", default="HW-01")
    p.add_argument("--experiments-dir", type=Path, default=None)
    p.add_argument("--synthetic", action="store_true", help="self-test without touching a camera")
    args = p.parse_args(argv)

    mode, _, value = args.exposure.partition(":")
    exposure_mode = mode.upper()
    exposure_value = float(value) if value else None
    backends = tuple(b.strip().upper() for b in args.backends.split(",") if b.strip())
    formats = [None if f.strip().lower() == "default" else f.strip().upper()
               for f in args.pixel_formats.split(",")]
    cfg = load_config(DEFAULT_BASE, DEFAULT_CAMERA)
    slug = "p02-enumerate-cameras" + ("-synthetic" if args.synthetic else "")
    with RunLog(phase="02", task="02.1", slug=slug, config=cfg, hardware_id=args.hardware_id,
                experiments_dir=args.experiments_dir,
                description="Task 02.1 device/backend/mode enumeration via OpenCV; values are "
                            "inspected/advertised by the driver, not measured.") as run:
        out: dict[str, Any] = {"label": "inspected / advertised by driver; NOT measured"}
        if args.synthetic:
            out.update({"pnp_cameras": [], "backends_available": [], "devices": [], "mode_probes": []})
            run.write_json_artefact("cameras.json", out)
            run.finish({"n_devices_opened": 0, "n_modes_probed": 0, "synthetic": True})
            print("RESULT: COMPLETED (synthetic)")
            return 0
        out["pnp_cameras"] = list_pnp_cameras()
        out["backends_available"] = available_backends()
        print("OS cameras:", out["pnp_cameras"])
        print("OpenCV camera backends:", out["backends_available"])
        out["devices"] = enumerate_devices(args.max_index, backends)
        for d in out["devices"]:
            print(f"{d['backend']:5s} index {d['index']}: {'opened' if d['opened'] else 'no device'}"
                  + (f" default {d['default_mode']['width']}x{d['default_mode']['height']} "
                     f"{d['default_mode']['fourcc']} fps_prop {d['default_mode']['fps_prop']} "
                     f"driver_ts={d['default_mode']['has_driver_timestamps']}" if d["opened"] else ""))
        out["mode_probes"] = []
        print("\n| backend | requested | pixel fmt req | negotiated | fourcc | fps_prop (advertised) | "
              "short unique-FPS probe (not a measurement) | mean lum |")
        print("|---|---|---|---|---|---|---|---|")
        for backend in backends:
            for fmt in formats:
                for (w, h, fps) in DEFAULT_MODES:
                    row = probe_mode(args.index, backend, w, h, fps, pixel_format=fmt,
                                     exposure_mode=exposure_mode, exposure_value=exposure_value)
                    out["mode_probes"].append(row)
                    if "error" in row:
                        print(f"| {backend} | {w}x{h}@{fps:g} | {fmt or 'default'} | "
                              f"ERROR {row['error']} | | | | |")
                        continue
                    n = row["negotiated"]
                    sp = row["short_probe"]
                    print(f"| {backend} | {w}x{h}@{fps:g} | {fmt or 'default'} | "
                          f"{n['width']}x{n['height']} | "
                          f"{n['fourcc']} | {n['fps_prop']} | {sp['unique_fps_short']:.1f} "
                          f"({sp['unique_frames']}/{sp['frames_read']}) | {sp['mean_luminance']:.0f} |")
        run.write_json_artefact("cameras.json", out)
        run.finish({
            "n_devices_opened": sum(1 for d in out["devices"] if d["opened"]),
            "n_modes_probed": len(out["mode_probes"]),
            "backends_available": out["backends_available"],
        })
        print(f"\nRESULT: COMPLETED {run.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
