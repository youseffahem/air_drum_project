"""TEST-PARITY-1: replay lossless raw sessions through the live loop and Phase 09 harness."""

import argparse
from pathlib import Path

from _p13 import begin_evidence, parity, read_plan, save_evidence

from spacedrums.app.main import Perception
from spacedrums.capture import ReplayFrameSource
from spacedrums.config import load_config
from spacedrums.prediction.model_loader import file_hash
from spacedrums.timing import now


def raw_frames(source, perception):
    for sample in source:
        view = source.view(sample)
        start = now()
        yield sample, perception(view), start


def causal_raw(cfg, source, baseline, session_id):
    from _p13 import compare_records, pipeline

    pipe = pipeline(cfg, session_id)
    perception = Perception(cfg)
    cut = len(baseline) // 2
    changed_suffix = 0
    try:
        for i, sample in enumerate(source):
            view = source.view(sample)
            if i >= cut:
                view.roi[:] = 0  # changes only a frame already delivered at/after the cut
            result = pipe.step(sample, perception(view), t_now=baseline[i].t_now)
            if pipe.model_error:
                raise ValueError(f"causality aborted by fallback: {pipe.model_error}")
            if i < cut:
                compare_records(result.commits, baseline[i].commits)
                for hand, hf in result.hands.items():
                    original = baseline[i].hands[hand]
                    compare_records([hf.features], [original.features], atol=1e-10, rtol=1e-10)
                    assert (hf.model_prediction is None) == (original.model_prediction is None)
                    if hf.model_prediction:
                        compare_records(
                            [hf.model_prediction], [original.model_prediction], ignored=("t_inference_done",)
                        )
                    compare_records(hf.candidates, original.candidates, ignored=("t_candidate",))
            else:
                changed_suffix += any(
                    result.hands[h].track != baseline[i].hands[h].track for h in result.hands
                )
    finally:
        perception.close()
    return {
        "test_id": "TEST-CAUSAL-1",
        "passed": True,
        "prefix_frames": cut,
        "perturbation": "black out delivered images at and after cut; original timestamps retained",
        "changed_suffix_frames": changed_suffix,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    started = begin_evidence()
    cfg, plan = load_config(args.config), read_plan(args.plan)
    rows = []
    for session in plan["sessions"]:
        source = ReplayFrameSource(session["path"])
        perception = Perception(cfg.data)
        try:
            frames = raw_frames(source, perception)
            report, results = parity(cfg.data, frames, session_id=session["id"])
            report["causality"] = causal_raw(cfg.data, source, results, session["id"])
            report.update(
                source_kind=session["kind"],
                frames_hash=file_hash(source.dir / "frames.jsonl"),
                image_hashes={s.image_ref.path: file_hash(source.dir / s.image_ref.path) for s in source},
            )
        except (ValueError, AssertionError, OSError, RuntimeError) as exc:
            report = {
                "session_id": session["id"],
                "source_kind": session["kind"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            perception.close()
        rows.append(report)
        print(f"{session['id']}: {'PASS' if report['passed'] else 'FAIL'}", flush=True)
    result = {
        "test_id": "TEST-PARITY-1",
        "source_kind": plan["source_kind"],
        "plan_hash": file_hash(args.plan),
        "config_hash": cfg.config_hash,
        "passed": all(r["passed"] for r in rows),
        "sessions": rows,
        "participant_fold_evidence": "PENDING" if plan["source_kind"] != "PARTICIPANT" else "executed",
    }
    save_evidence(args.output, "parity.json", result, started=started)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
