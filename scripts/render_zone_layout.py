"""Render candidate zone geometry and profile overlay compute cost."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from _runlog import RunLog  # noqa: E402

from spacedrums.config import load_config  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.ui.zones import draw_zones  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", type=Path, default=ROOT / "configs/zones/mvp4.candidate.yaml")
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Required acknowledgement: blank image is synthetic, not a capture",
    )
    args = parser.parse_args()
    if not args.synthetic:
        parser.error("rendering evidence uses a blank synthetic ROI; pass --synthetic")
    config = load_config(ROOT / "configs/example.candidate.yaml", args.layout)
    registry = ZoneRegistry.load(args.layout)
    blank = np.full((720, 960, 3), 24, np.uint8)
    timings = []
    rendered = blank
    with RunLog(
        phase="04",
        task="04.11",
        slug="p04-layout-render",
        description="SYNTHETIC blank-ROI zone overlay and compute profile",
        config=config,
    ) as run:
        for _ in range(args.iterations):
            start = perf_counter()
            rendered = draw_zones(blank, registry)
            timings.append((perf_counter() - start) * 1000)
        out = run.dir / "mvp4-layout-synthetic.png"
        if not cv2.imwrite(str(out), rendered):
            raise RuntimeError(f"failed to write {out}")
        run.add_artefact(out, "figure")
        ordered = sorted(timings)
        metrics = {
            "iterations": len(timings),
            "overlay_compute_ms_p50": statistics.median(timings),
            "overlay_compute_ms_p95": ordered[int(0.95 * (len(ordered) - 1))],
            "input": "SYNTHETIC blank 960x720 ROI",
            "zones": len(registry),
        }
        run.finish(metrics, notes="Development measurement; dirty-tree status is recorded honestly.")
        print(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
