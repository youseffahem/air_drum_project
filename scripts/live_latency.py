"""Measure software stages in the application loop; live and replay evidence stay distinct."""

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
from _p13 import begin_evidence, save_evidence

from spacedrums.app.main import build_parser, run


def percentiles(values):
    return {
        "n": len(values),
        **{f"p{p}_s": float(np.percentile(values, p)) if values else None for p in (50, 95, 99)},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--source", choices=("live", "replay"), required=True)
    ap.add_argument("--session-dir", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--switch-frame", type=int, default=150)
    args = ap.parse_args()
    started = begin_evidence()
    cli = [
        "--config",
        str(args.config),
        "--source",
        args.source,
        "--arm",
        "A",
        "--shadow",
        "B",
        "C-GRU",
        "--record",
        "--output-dir",
        str(args.output / "sessions"),
        "--no-window",
        "--no-audio",
        "--max-frames",
        str(args.max_frames),
        "--max-seconds",
        "60",
    ]
    # Explicit variant from the config; never guess a shipped family.
    from spacedrums.config import load_config

    cfg = load_config(args.config)
    cli[cli.index("C-GRU")] = "C-" + cfg["anticipator"]["model"]["family"].upper()
    if args.session_dir:
        cli += ["--session-dir", str(args.session_dir)]
    app_args = build_parser().parse_args(cli)
    rows, strikes, switches = [], [], []

    def hook(sample, result, pipe):
        inference = {}
        for hand, hf in result.hands.items():
            if hf.model_prediction and pipe.model_arm and hand in pipe.model_arm.stamps:
                inference[str(hand)] = dict(pipe.model_arm.stamps[hand])
        rows.append(
            {
                "frame_id": sample.frame_id,
                "active_arm": str(pipe.active_arm),
                "capture": sample.t_capture,
                "available": sample.t_frame_available,
                "decision": result.t_now,
                "dropped": sample.dropped_since_last,
                "model": inference,
                "fallback_count": len(pipe.fallback_events),
            }
        )
        strikes.extend(t.to_dict() for t in result.timing if t.kind == "STRIKE")
        if len(rows) == args.switch_frame:
            try:
                pipe.set_active_arm(pipe.model_label, result.t_now)
                switches.append({"frame": sample.frame_id, "result": "switched to model"})
            except ValueError as exc:
                switches.append({"frame": sample.frame_id, "result": str(exc)})
        return True

    summary = run(app_args, on_frame=hook)
    grouped = defaultdict(list)
    for row in rows:
        for stamps in row["model"].values():
            grouped[row["active_arm"]].append(stamps["inference_s"])
    terms = defaultdict(lambda: defaultdict(list))
    pairs = [
        ("capture_to_available", "t_capture", "t_frame_available"),
        ("available_to_tracking", "t_frame_available", "t_tracking_done"),
        ("tracking_to_features", "t_tracking_done", "t_features_done"),
        ("features_to_inference", "t_features_done", "t_inference_done"),
        ("inference_to_candidate", "t_inference_done", "t_candidate"),
        ("candidate_to_commit", "t_candidate", "t_commit"),
        ("commit_to_schedule", "t_commit", "t_audio_scheduled"),
        ("capture_to_commit", "t_capture", "t_commit"),
    ]
    if args.source == "live":
        for strike in strikes:
            for name, a, b in pairs:
                if strike[a] is not None and strike[b] is not None:
                    terms[strike["arm"]][name].append(strike[b] - strike[a])
    report = {
        "evidence": "MEASURED developer live software timing"
        if args.source == "live"
        else "MEASURED developer REPLAY COMPUTE; not live timing",
        "source": args.source,
        "config_hash": cfg.config_hash,
        "summary": summary,
        "frames": rows,
        "strikes": strikes,
        "switches": switches,
        "inference_by_active_arm": {k: percentiles(v) for k, v in grouped.items()},
        "software_decomposition": {
            arm: {k: percentiles(v) for k, v in group.items()} for arm, group in terms.items()
        },
        "drops_by_active_arm": {
            arm: sum(r["dropped"] for r in rows if r["active_arm"] == arm)
            for arm in {r["active_arm"] for r in rows}
        },
        "audio": "software scheduler only; no device or acoustic timing",
        "live_strike_evidence_complete": args.source == "live"
        and any(s["arm"].startswith("C-") for s in strikes),
        "delta_proc_policy": "per-frame capture-to-decision; candidate fixed constants unchanged; "
        "material if p95 changes by >=1 ms or any commit set changes: rerun offline",
    }
    path = save_evidence(args.output, "live-timing.json", report, started=started)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
