"""Audit saved developer measurements through the demo pipeline, silently and causally.

This is observation replay, NOT live physical verification and NOT a demo launcher.
No camera, speaker, learned model, synthetic trajectory or future frame is used.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.play import play_config
from spacedrums.config import config_hash
from spacedrums.contracts import FrameSample, HandId, HandObservation, StickObservation
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.geometry import ZoneRegistry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cfg = play_config(demo=True)
    current = [0.0]
    audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=False,
                        clock=lambda: current[0])
    pipeline = DecisionPipeline(
        cfg, registry=ZoneRegistry.from_config(cfg["zones"]), session_id="DEVELOPER-OBSERVATION-REPLAY",
        active_arm="A", hardware_id="offline", config_hash=config_hash(cfg), audio=audio,
        clock=lambda: current[0], developer_demo=True,
    )
    reasons, strokes, gates, counts = (Counter() for _ in range(4))
    events = []
    frames = 0
    with (args.session / "observations.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            sample = FrameSample.from_dict(row["frame"])
            if tuple(sample.roi_px) != tuple(cfg["roi"]["px"]):
                raise ValueError("saved observation coordinates do not match the fixed demo ROI")
            hands = {HandId(h["hand_id"]): HandObservation.from_dict(h) for h in row["hands"]}
            sticks = {HandId(s["hand_id"]): StickObservation.from_dict(s) for s in row["sticks"]}
            evidence = {}
            for e in row["endpoints"]:
                e = {k: v for k, v in e.items() if k != "schema_version"}
                for key in ("tip", "origin"):
                    if e.get(key) is not None:
                        e[key] = tuple(e[key])
                evidence[HandId(e["hand_id"])] = EndpointEvidence(**e)
            current[0] = sample.t_frame_available
            result = pipeline.step(sample, {h: (hands[h], sticks[h]) for h in HandId},
                                   t_now=current[0], endpoint_evidence=evidence)
            frames += 1
            reasons.update(e.reason for e in evidence.values())
            strokes.update(d["reason"] for d in pipeline.geometry.diagnostics.values())
            gates.update(g["decision"] for hf in result.hands.values() for g in hf.decision_traces)
            counts.update(c.zone_id for c in result.commits)
            events.extend({"commit": c.to_dict(), "audio": e.to_dict()}
                          for c, e in zip(result.commits, result.audio, strict=True))
    report = {
        "provenance": "DEVELOPER_SAVED_OBSERVATION_REPLAY", "source": str(args.session),
        "participant_evidence": False, "live_physical_verification": "NOT_YET_VERIFIED",
        "new_perception_run": False, "sound_played": False, "live_fps": None,
        "config": cfg, "config_hash": config_hash(cfg), "frames": frames,
        "endpoint_reasons": dict(reasons), "stroke_reasons": dict(strokes),
        "commit_gates": dict(gates), "commits_by_drum": dict(counts), "events": events,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("config", "events")}, indent=2))


if __name__ == "__main__":
    main()
