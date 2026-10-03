"""Read a developer product capture; quantify visibility and standing-reference failures."""

from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from pathlib import Path

import cv2
import numpy as np

from spacedrums.capture import ReplayFrameSource
from spacedrums.hands.body import BodyLandmarker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    rows = [json.loads(s) for s in (args.session / "observations.jsonl").read_text().splitlines()]
    active = [r for r in rows if any(h["present"] for h in r["hands"])]
    out = {
        "provenance": "DEVELOPER_REPLAY",
        "participant_evidence": False,
        "frames": len(rows),
        "frames_with_any_hand": len(active),
        "both_hands_in_active_frames": sum(all(h["present"] for h in r["hands"]) for r in active),
        "both_measured_tips_in_active_frames": sum(
            all(e["kind"] == "MEASURED" for e in r["endpoints"]) for r in active
        ),
        "active_endpoint_reasons": dict(Counter(e["reason"] for r in active for e in r["endpoints"])),
        "active_first_frame": active[0]["frame"]["frame_id"] if active else None,
        "active_last_frame": active[-1]["frame"]["frame_id"] if active else None,
        "active_fps": (
            (len(active) - 1) / (active[-1]["frame"]["t_capture"] - active[0]["frame"]["t_capture"])
        )
        if len(active) > 1
        else None,
        "body_samples": [],
        "standing_gate_counts": {},
    }
    out["stages"] = {}
    for state in sorted({r["state"] for r in rows}):
        group = [r for r in rows if r["state"] == state]
        out["stages"][state] = {
            "frames": len(group),
            "both_hands": sum(all(h["present"] for h in r["hands"]) for r in group),
            "both_measured_tips": sum(all(e["kind"] == "MEASURED" for e in r["endpoints"]) for r in group),
            "endpoint_reasons": dict(Counter(e["reason"] for r in group for e in r["endpoints"])),
        }
    if not (args.session / "frames.jsonl").exists():
        out["pose_replay"] = "Unavailable: raw frames were not recorded."
        (args.session / "diagnosis.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(out, indent=2))
        return
    pose = BodyLandmarker("mediapipe-pose-landmarker-full-float16-v1")
    last = -float("inf")
    bodies = deque(maxlen=16)
    gates = Counter()
    for view in ReplayFrameSource(args.session).views():
        if not active or view.sample.frame_id < out["active_first_frame"]:
            continue
        if view.sample.t_capture - last < 0.2:
            continue
        last = view.sample.t_capture
        body = pose.detect(view)
        if body is None:
            gates["pose_missing"] += 1
            continue
        out["body_samples"].append(body.to_dict())
        bodies.append(body)
        if len(bodies) < 10:
            gates["warming_up"] += 1
            continue
        values = np.array([[b.left, b.right, b.shoulder_y, b.hip_y] for b in bodies])
        left, right, sy, hy = np.median(values, axis=0)
        if np.max(np.ptp(values, axis=0)) > 0.06:
            gates["unstable_range"] += 1
        elif abs((left + right) / 2 - 0.5) > 0.08 or sy < 0.05 or hy > 0.98:
            gates["outside_standing_bounds"] += 1
        else:
            gates["body_gate_pass"] += 1
    pose.close()
    out["standing_gate_counts"] = dict(gates)
    if out["body_samples"]:
        out["body_medians"] = {
            k: float(np.median([b[k] for b in out["body_samples"]]))
            for k in ("left", "right", "shoulder_y", "hip_y", "confidence")
        }
    path = args.session / "diagnosis.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "body_samples"}, indent=2))


if __name__ == "__main__":
    main()
