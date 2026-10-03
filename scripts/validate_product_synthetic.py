"""SYNTHETIC product decision/audio regression report, not physical strike evidence."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import DecisionPipeline
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.config import config_hash, load_config
from spacedrums.contracts import Arm, HandId, TipMethod
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.four_pad import DISPLAY_ORDER, four_pad_layout


def evaluate(cfg, name, swings, duration=3.0, noise=0.0):
    registry = ZoneRegistry.from_config(cfg["zones"])
    seq = build_sequence(registry, swings, duration_s=duration, noise=noise)
    clock = [100.0]
    audio = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=False, clock=lambda: clock[0])
    pipeline = DecisionPipeline(
        cfg,
        registry=registry,
        session_id="SYNTHETIC-" + name,
        active_arm=Arm.A,
        hardware_id="developer-host",
        config_hash=config_hash(cfg),
        audio=audio,
        clock=lambda: clock[0],
    )
    hits, simultaneous = [], 0
    for sample, original in seq:
        clock[0] = sample.t_frame_available
        obs = {h: (o, replace(s, method_id=TipMethod.AXIS_REFINED)) for h, (o, s) in original.items()}
        ev = {
            h: EndpointEvidence(
                sample.frame_id,
                sample.t_capture,
                h,
                "MEASURED" if s.present else "MISSING",
                "SYNTHETIC",
                s.tip,
                s.axis_origin,
                s.tip_confidence,
            )
            for h, (o, s) in obs.items()
        }
        result = pipeline.step(sample, obs, t_now=clock[0], endpoint_evidence=ev)
        simultaneous += len(result.commits) == 2
        for c in result.commits:
            candidates = result.hands[c.hand_id].reactive
            impact = next(x.t_impact_est for x in candidates if x.candidate_id == c.candidate_id)
            hits.append((str(c.hand_id), c.zone_id, impact))
    remaining = list(hits)
    matched = 0
    for truth in seq.truth:
        matches = [
            (i, abs(t - truth.t_cross))
            for i, (hand, zone, t) in enumerate(remaining)
            if hand == str(truth.hand) and zone == truth.zone_id and abs(t - truth.t_cross) <= 1 / 30
        ]
        if matches:
            i, _ = min(matches, key=lambda pair: pair[1])
            remaining.pop(i)
            matched += 1
    return {
        "scenario": name,
        "expected": len(seq.truth),
        "matched": matched,
        "missed": len(seq.truth) - matched,
        "false_hits": len(remaining),
        "audio_events": audio.events,
        "simultaneous_frames": simultaneous,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cfg = load_config("configs/prototype.candidate.yaml", "configs/product.candidate.yaml").data
    cfg["zones"] = four_pad_layout((0.2, 0.8), (0.30, 0.65), 0.15, 0.10)
    L, R = HandId.LEFT, HandId.RIGHT
    results = []
    for h in (L, R):
        for z in DISPLAY_ORDER:
            results.append(evaluate(cfg, f"single-{h}-{z}", [Swing(h, z, 0.3)], duration=1.1))
    for name, offset in (("simultaneous", 0.0), ("alternating-roll", 2 / 30)):
        swings = [
            Swing(h, z, 0.3 + i * 4 / 30 + o, t_down=1 / 30, depth=0.12)
            for i in range(10)
            for h, z, o in ((L, "snare", 0.0), (R, "crash_ride", offset))
        ]
        results.append(evaluate(cfg, name, swings))
    results.append(
        evaluate(
            cfg,
            "same-hand-7.5-Hz",
            [Swing(R, "snare", 0.3 + i * 4 / 30, t_down=1 / 30, depth=0.12) for i in range(10)],
        )
    )
    for kind in ("hover", "lateral", "upward", "stop_short"):
        results.append(
            evaluate(
                cfg, kind, [Swing(R, "snare", 0.3, kind=kind, depth=-0.02 if kind == "stop_short" else 0.05)]
            )
        )
    results.append(evaluate(cfg, "rest-jitter", [Swing(R, "snare", 0.3, kind="hover")], noise=0.002))
    report = {
        "provenance": "SYNTHETIC",
        "participant_evidence": False,
        "matching_tolerance_s": 1 / 30,
        "sampling_fps": 30,
        "measured_camera_fps": None,
        "cases": results,
        "passed": all(r["missed"] == r["false_hits"] == 0 for r in results),
        "limitation": "Rendered observations bypass perception. Physical recall and false-hit rates unknown.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
