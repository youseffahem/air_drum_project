"""Record deterministic injected-fault transitions; synthetic trace, never live measurements."""

import argparse
import copy
from pathlib import Path

from _p13 import begin_evidence, pipeline, save_evidence

from spacedrums.app.arms import build_model_arm
from spacedrums.app.synthetic import scenario
from spacedrums.config import load_config
from spacedrums.geometry import ZoneRegistry


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    started = begin_evidence()
    cfg = load_config(args.config).data
    rows = []
    for fault in (
        "missing_model",
        "missing_stats",
        "wrong_hash",
        "slow_model",
        "total_processing",
        "B_unavailable",
    ):
        c = copy.deepcopy(cfg)
        c["anticipator"]["fallback"].update(enabled=True, window_frames=1)
        if fault in ("missing_model", "B_unavailable"):
            c["anticipator"]["model"]["path"] += "/missing"
        if fault == "B_unavailable":
            c["anticipator"]["rule"] = None
        if fault == "missing_stats":
            c["anticipator"]["model"]["norm_stats_path"] += ".missing"
        if fault == "wrong_hash":
            c["anticipator"]["model"]["hash"] = "sha256:" + "0" * 64
        ticks = [100.0]

        def clock(ticks=ticks):
            return ticks[0]

        def factory(config, clock, ticks=ticks, fault=fault):
            arm = build_model_arm(config, clock=clock)
            predict = arm.adapter.predict

            def slow(*a):
                ticks[0] += 0.1
                return predict(*a)

            if fault == "slow_model":
                arm.adapter.predict = slow
            return arm

        pipe = pipeline(c, "fault-" + fault, clock=clock, model_factory=factory)
        frames = scenario("single", ZoneRegistry.from_config(c["zones"]))
        commits = []
        for i, (sample, obs) in enumerate(frames):
            result = pipe.step(
                sample,
                obs,
                t_now=sample.t_frame_available,
                processing_started=99.0 if fault == "total_processing" else clock(),
            )
            commits.extend(s.to_dict() for s in result.commits)
            if i == 1:
                break
        expected = "A" if fault == "B_unavailable" else "B"
        passed = pipe.active_arm == expected and len(pipe.fallback_events) == 1 and not commits
        rows.append(
            {
                "fault": fault,
                "passed": passed,
                "expected_target": expected,
                "events": pipe.fallback_events,
                "commits": commits,
                "counters": pipe.counters(),
            }
        )
    report = {
        "evidence": "SYNTHETIC injected fault trace with controlled clock",
        "passed": all(r["passed"] for r in rows),
        "cases": rows,
    }
    save_evidence(args.output, "faults.json", report, started=started)
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {len(rows)} fault cases")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
