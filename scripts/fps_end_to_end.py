"""Summarize an actual profiled live run, or record a camera-blocked native-FPS target.

Never promotes replay capacity, advertised FPS, duplication or interpolation to native FPS.
"""

import argparse
import json
import math
from pathlib import Path

from _p10 import provenance, write_json

from spacedrums.models.temporal.data import sha


def assess(profile, samples, target):
    if profile["source"] != "live" or profile["kind"] != "wall-time profile":
        raise ValueError("only a live wall-time profile can establish delivered FPS")
    rows = []
    for sample in samples:
        n = len(sample["rows"])
        fps = sample["delivered_processing_fps"]
        captures = sample["application"]["source"].get("capture_stats") or {}
        model_frames = sum(r["active_arm"].startswith("C-") and r["fallback"] is None for r in sample["rows"])
        prediction_frames = sum(r.get("predictions", 0) > 0 for r in sample["rows"])
        ids = [r.get("frame_id") for r in sample["rows"]]
        stamps = [r.get("t_capture") for r in sample["rows"]]
        unique_delivery = bool(
            n > 1
            and None not in ids
            and len(set(ids)) == n
            and all(t is not None and math.isfinite(t) for t in stamps)
            and all(b > a for a, b in zip(stamps, stamps[1:], strict=False))
            and captures.get("duplicates", 0) == 0
        )
        rows.append(
            {
                "frames": n,
                "delivered_processing_fps": fps,
                "processing_p95_ms": sample["processing"]["p95_ms"],
                "drops": sample["capture_drops"],
                "capture_stats": captures,
                "model_active_fraction": model_frames / n if n else 0,
                "prediction_frames": prediction_frames,
                "unique_delivery": unique_delivery,
                "target_met": bool(
                    fps is not None
                    and math.isfinite(fps)
                    and unique_delivery
                    and fps >= target * 0.95
                    and sample["capture_drops"] / max(n, 1) <= 0.01
                    and model_frames == n
                    and prediction_frames > 0
                ),
            }
        )
    return {
        "target_fps": target,
        "runs": rows,
        "target_met": bool(rows) and all(r["target_met"] for r in rows),
        "criterion": ">=95% target unique FPS; <=1% drops; model active throughout with nonempty predictions",
        "native_60fps_claim": target == 60 and bool(rows) and all(r["target_met"] for r in rows),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--target", type=int, choices=(30, 60), required=True)
    parser.add_argument("--camera-blocked", action="store_true")
    parser.add_argument("--camera-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output exists; preserve previous FPS evidence")
    if not args.camera_evidence.is_file():
        parser.error("camera evidence must exist")
    if args.camera_blocked:
        if args.profile_dir or args.target != 60:
            parser.error("blocked path is only for unavailable native 60 FPS, without a profile")
        result = {
            "status": "PENDING",
            "target_fps": 60,
            "native_60fps_claim": False,
            "reason": "Phase 02 reports no native 60 FPS; repeat Phase 02 on a capable camera first",
            "dt_step_policy": "model rate must match; cadence guard refuses mismatches; no interpolation",
        }
    else:
        if not args.profile_dir:
            parser.error("provide a live --profile-dir or --camera-blocked")
        profile = json.loads((args.profile_dir / "profile.json").read_text(encoding="utf-8"))
        samples = [
            json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.profile_dir.glob("sample-*.json"))
        ]
        result = assess(profile, samples, args.target)
        result["profile_hash"] = sha(args.profile_dir / "profile.json")
        result["status"] = "ACHIEVED" if result["target_met"] else "SHORTFALL"
    write_json(
        args.output,
        {
            **provenance(),
            **result,
            "camera_evidence": str(args.camera_evidence),
            "camera_evidence_hash": sha(args.camera_evidence),
        },
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
