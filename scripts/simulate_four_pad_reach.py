"""Replay the product reach fit, or audit historical evidence for eligibility.

Usage: python scripts/simulate_four_pad_reach.py --session DIR --output FILE
Produces a deliberately failed evidence gate when measured stroke endpoints are absent.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from spacedrums.calib.reach import ReachSettings, ReachStroke, fit_reach
from spacedrums.contracts.perception import BodyReference
from spacedrums.contracts.schema import validator


def audit(session: Path) -> dict:
    rows = [
        json.loads(line) for line in (session / "records/StickObservation.jsonl").read_text().splitlines()
    ]
    rows = [r for r in rows if "method_id" in r]
    counts = Counter(r["method_id"] for r in rows)
    axis = [r for r in rows if r["present"] and r["axis_confidence"] >= 0.65]
    tips = np.asarray([r["tip"] for r in axis])
    # AXIS_REFINED legacy records do not identify whether a GEOM fallback was used.
    # They too require an EndpointEvidence companion before admission.
    return {
        "provenance": "DEVELOPER_REPLAY",
        "source": str(session),
        "hand_frames": len(rows),
        "methods": dict(counts),
        "axis_confident_frames": len(axis),
        "legacy_tip_p05_p95": np.percentile(tips, [5, 95], axis=0).tolist() if len(tips) else None,
        "measured_endpoint_strokes_admitted": 0,
        "feasible": False,
        "reason": "Historical tip records do not certify visible endpoints or per-target strokes.",
        "required_minimum_height_px": 2 * 42 + 32 + 2 * 10,
        "participant_evidence": False,
    }


def simulate(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    calibration = report.get("calibration", report)
    validator("product-calibration").validate(calibration)
    result = {
        "provenance": "SYNTHETIC" if calibration["provenance"] == "SYNTHETIC" else "DEVELOPER_REPLAY",
        "source_provenance": calibration["provenance"],
        "participant_evidence": False,
        "source": str(report_path),
        "measured_endpoint_strokes_admitted": len(calibration["strokes"]),
        "feasible": False,
        "fit": None,
    }
    if calibration["body"] is None:
        return {**result, "reason": "No stable standing reference was established."}
    body = BodyReference(**calibration["body"])
    strokes = [ReachStroke(**s) for s in calibration["strokes"]]
    fit = fit_reach(strokes, body, tuple(calibration["roi_size"]), ReachSettings(**calibration["settings"]))
    return {
        **result,
        "feasible": fit["passed"],
        "fit": fit,
        "reason": "Constrained fit from recorded measured strokes; physical accuracy remains unverified.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", type=Path, help="Historical developer session")
    source.add_argument("--report", type=Path, help="Product report or product-calibration JSON")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = simulate(a.report) if a.report else audit(a.session)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
