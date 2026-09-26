"""Phase 14 repeatability analysis (Task 14.3 / Experimental Design): repeated calibrations, ONE subject.

    python scripts/calibration_repeatability.py --calibrations data/calibration/dev-*.calib.yaml \\
        --output-dir experiments/phase-14/<run>/repeatability [--tolerance 0.05]

Reports per hand the spread of L_prior (mean, SD, range, CV) and whether every consecutive pair agrees
within ``--tolerance`` (relative; a CANDIDATE, To Be Experimentally Determined), plus the spread of the
fitted layout (scale, translation, every zone centre), the reach envelope, wizard durations and the
Arm A validation detections. It refuses calibrations that do not share one subject, camera profile,
ROI and template layout.

Label discipline: the result is MEASURED only when every input is a DEVELOPER_LIVE or PARTICIPANT_LIVE
calibration (a person followed the wizard); any SYNTHETIC input makes the whole report a SYNTHETIC
machinery check and DEVELOPER_REPLAY inputs make it a development diagnostic. Nothing is fabricated.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from spacedrums.calib import load_calibration

HANDS = ("LEFT", "RIGHT")


def spread(values: list[float]) -> dict[str, Any]:
    n = len(values)
    mean = statistics.fmean(values) if n else None
    sd = statistics.stdev(values) if n > 1 else None
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "min": min(values) if n else None,
        "max": max(values) if n else None,
        "range": (max(values) - min(values)) if n else None,
        "cv": (sd / mean) if sd is not None and mean else None,
    }


def label_for(kinds: set[str]) -> str:
    if "SYNTHETIC" in kinds:
        return "SYNTHETIC machinery check - never evidence"
    if "DEVELOPER_REPLAY" in kinds:
        return "DEVELOPMENT DIAGNOSTIC (replayed frames, no cued behaviour)"
    return "MEASURED"


def analyse(paths: list[Path], tolerance: float) -> dict[str, Any]:
    calibs = [load_calibration(p) for p in paths]
    if len(calibs) < 2:
        raise SystemExit("repeatability needs at least two calibrations")
    keys = {
        (
            c.doc["provenance"]["scope"],
            c.doc["provenance"]["user_tag"],
            c.doc["provenance"]["setup_tag"],
            c.doc["camera"]["profile_hash"],
            tuple(c.doc["roi"]["px"]),
            c.doc["layout"]["template"]["zones_hash"],
            c.doc["layout"]["fit"]["mode"],
        )
        for c in calibs
    }
    if len(keys) != 1:
        raise SystemExit("calibrations differ in subject, camera profile, ROI, template or fit mode")
    kinds = {c.doc["provenance"]["kind"] for c in calibs}
    out: dict[str, Any] = {
        "label": label_for(kinds),
        "provenance_kinds": sorted(kinds),
        "calibrations": [
            {
                "path": str(p),
                "calibration_id": c.calibration_id,
                "hash": c.hash,
                "created_at": c.doc["created_at"],
                "git_sha": c.doc["app"]["git_sha"],
                "git_dirty": c.doc["app"]["git_dirty"],
            }
            for p, c in zip(paths, calibs, strict=True)
        ],
        "tolerance_rel": tolerance,
        "tolerance_label": "candidate (To Be Experimentally Determined)",
    }
    l_prior = {}
    for hand in HANDS:
        values = [float(c.doc["stick_prior"]["l_prior"][hand]) for c in calibs]
        sources = [c.doc["stick_prior"]["per_hand"][hand]["source"] for c in calibs]
        pairs = []
        for i in range(len(values) - 1):
            a, b = values[i], values[i + 1]
            rel = abs(a - b) / ((a + b) / 2)
            pairs.append(
                {
                    "pair": [i, i + 1],
                    "abs_diff": abs(a - b),
                    "rel_diff": rel,
                    "within_tolerance": rel <= tolerance,
                }
            )
        l_prior[hand] = {
            "values": values,
            "sources": sources,
            "measured_only": all(s == "MEASURED" for s in sources),
            **spread(values),
            "consecutive_pairs": pairs,
            "all_pairs_within_tolerance": all(p["within_tolerance"] for p in pairs),
        }
    out["l_prior"] = l_prior
    fits = [c.doc["layout"]["fit"] for c in calibs]
    out["fit"] = {
        "scale": spread([float(f["scale"]) for f in fits]),
        "translate_x": spread([float(f["translate"][0]) for f in fits]),
        "translate_y": spread([float(f["translate"][1]) for f in fits]),
    }
    zones: dict[str, Any] = {}
    for idx, zone in enumerate(calibs[0].doc["layout"]["zones"]):
        centres = [c.doc["layout"]["zones"][idx]["shape"].get("center") for c in calibs]
        if any(v is None for v in centres):
            continue
        xs, ys = [float(v[0]) for v in centres], [float(v[1]) for v in centres]
        zones[zone["zone_id"]] = {
            "centre_x": spread(xs),
            "centre_y": spread(ys),
            "max_centre_shift": max(math.dist((xs[0], ys[0]), (x, y)) for x, y in zip(xs, ys, strict=True)),
        }
    out["zone_centres"] = zones
    boxes = [c.doc["reach_envelope"]["box"] for c in calibs if c.doc["reach_envelope"]["box"] is not None]
    out["envelope"] = {
        name: spread([float(b[i]) for b in boxes]) for i, name in enumerate(("x0", "y0", "x1", "y1"))
    }
    out["durations_total_s"] = spread(
        [float(c.doc["durations_s"]["total"]) for c in calibs if c.doc["durations_s"]["total"] is not None]
    )
    out["duration_clock"] = sorted({c.doc["durations_s"]["clock"] for c in calibs})
    out["validation"] = [
        {
            "calibration_id": c.calibration_id,
            "status": c.doc["validation"]["status"],
            "passed": c.doc["validation"]["passed"],
            "detections": {r["zone_id"]: [r["detected"], r["cued"]] for r in c.doc["validation"]["per_zone"]},
        }
        for c in calibs
    ]
    return out


def markdown(r: dict[str, Any]) -> str:
    def f(v: Any, nd: int = 4) -> str:
        return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))

    lines = [
        f"# Calibration repeatability - {r['label']}",
        "",
        f"Inputs: {len(r['calibrations'])} calibrations ({', '.join(r['provenance_kinds'])}); "
        f"tolerance {r['tolerance_rel']} relative ({r['tolerance_label']}).",
        "",
        "| hand | values | mean | SD | range | CV | sources | consecutive pairs within tolerance |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for hand, s in r["l_prior"].items():
        vals = ", ".join(f(v) for v in s["values"])
        ok = sum(p["within_tolerance"] for p in s["consecutive_pairs"])
        lines.append(
            f"| {hand} | {vals} | {f(s['mean'])} | {f(s['sd'])} | {f(s['range'])} | {f(s['cv'])} | "
            f"{', '.join(sorted(set(s['sources'])))} | {ok}/{len(s['consecutive_pairs'])} |"
        )
    lines += ["", "| layout quantity | mean | SD | range |", "|---|---|---|---|"]
    for name, s in r["fit"].items():
        lines.append(f"| fit {name} | {f(s['mean'])} | {f(s['sd'])} | {f(s['range'])} |")
    for zone, s in r["zone_centres"].items():
        lines.append(f"| {zone} centre shift (max) | - | - | {f(s['max_centre_shift'])} |")
    d = r["durations_total_s"]
    lines += [
        "",
        f"Wizard duration (clock {', '.join(r['duration_clock'])}): mean {f(d['mean'], 1)} s, "
        f"range {f(d['range'], 1)} s over {d['n']} runs.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibrations", nargs="+", type=Path, required=True)
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    result = analyse(args.calibrations, args.tolerance)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "repeatability.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "repeatability.md").write_text(markdown(result), encoding="utf-8")
    print(
        f"[repeatability] {result['label']}: "
        + "; ".join(
            f"{h} L mean {v['mean']:.4f} SD {v['sd']:.5f} pairs-ok {v['all_pairs_within_tolerance']}"
            for h, v in result["l_prior"].items()
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
