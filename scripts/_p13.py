"""Phase 13 evidence helpers. Raw replay is developer evidence, never live timing."""

import json
from pathlib import Path

import numpy as np
from _p10 import provenance, source_hashes, write_json

from spacedrums.app.arms import build_model_arm
from spacedrums.app.pipeline import HANDS, DecisionPipeline
from spacedrums.contracts.schema import validate
from spacedrums.eval.replay import DelayPolicy, replay
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.geometry import ZoneRegistry
from spacedrums.timing import now, wall_clock_iso


def execution():
    return {
        **provenance(),
        "codex_model": "UNVERIFIED",
        "codex_reasoning_effort": "UNVERIFIED",
        "setting_evidence": "Picker settings unverified by agent and user; user instructed no inference.",
    }


def pipeline(cfg, session_id, *, clock=now, active=None, shadows=("A", "B"), model_factory=build_model_arm):
    arm = "C-" + cfg["anticipator"]["model"]["family"].upper()
    return DecisionPipeline(
        cfg,
        registry=ZoneRegistry.from_config(cfg["zones"]),
        session_id=session_id,
        active_arm=active or arm,
        shadow_arms=shadows,
        hardware_id="HW-01",
        config_hash="sha256:" + "0" * 64,
        audio=None,
        gain_fn=lambda _z, _v: 1.0,
        clock=clock,
        model_factory=model_factory,
    )


def compare_records(actual, expected, *, ignored=(), atol=1e-6, rtol=1e-5):
    """Compare complete ordered records; only declared clocks/assigned identifiers may differ."""
    if len(actual) != len(expected):
        raise AssertionError(f"record count mismatch: live={len(actual)}, offline={len(expected)}")
    maximum = 0.0

    def visit(a, b, path):
        nonlocal maximum
        if isinstance(a, dict) and isinstance(b, dict):
            assert a.keys() == b.keys(), path
            for k in a:
                if k not in ignored:
                    visit(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            assert len(a) == len(b), path
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                visit(x, y, f"{path}[{i}]")
        elif isinstance(a, float) or isinstance(b, float):
            assert a is not None and b is not None, path
            name = path.rsplit(".", 1)[-1]
            absolute_time = name.startswith("t_") or name == "refractory_until"
            # A large monotonic epoch must never enlarge the allowed timing error.
            np.testing.assert_allclose(a, b, atol=atol, rtol=0 if absolute_time else rtol, err_msg=path)
            maximum = max(maximum, abs(float(a) - float(b)))
        else:
            assert a == b, f"{path}: {a!r} != {b!r}"

    for i, (a, b) in enumerate(zip(actual, expected, strict=True)):
        visit(a.to_dict(), b.to_dict(), str(i))
    return {"records": len(actual), "max_abs_deviation": maximum, "atol": atol, "rtol": rtol}


def parity(cfg, frames, *, session_id, measured_delay=True, clock=now):
    """Live production loop vs independent Phase 09 replay state on its delivered tracks.

    Raw video perception is supplied by the caller; future frames are never passed to the loop.
    The offline harness starts fresh and independently assembles windows from reference features.
    """
    pipe = pipeline(cfg, session_id, clock=clock)
    if pipe.model_arm is None or pipe.model_error:
        raise ValueError(f"parity requires an available model: {pipe.model_error}")
    model = build_model_arm(cfg, clock=clock)
    reference = StreamingFeatures(model.stream.schema, history_n=model.manifest["N"])
    tracks, reference_features, results, drops, delays = [], [], [], {}, {}
    for item in frames:
        sample, observations = item[:2]
        start = item[2] if len(item) == 3 else clock()
        result = pipe.step(
            sample,
            observations,
            processing_started=start,
            replay_measured=measured_delay,
            t_now=None if measured_delay else sample.t_frame_available,
        )
        if pipe.model_error:
            raise ValueError(f"parity aborted by fallback: {pipe.model_error}")
        results.append(result)
        delays[sample.frame_id] = result.t_now - sample.t_capture
        drops[sample.frame_id] = sample.dropped_since_last
        for h in HANDS:
            t = result.hands[h].track
            tracks.append(t)
            if t.reset_reason is not None:
                reference.reset(h)
            reference_features.append(
                reference.update(t, hand=observations[h][0], stick=observations[h][1], frame=sample)
            )
    if not results:
        raise ValueError("empty parity session")
    offline = replay(
        tracks,
        arm="MODEL:" + str(pipe.model_label),
        registry=pipe.registry,
        commit_settings=pipe.commit_settings_by_arm[pipe.model_label],
        v_min=pipe.geometry_by_arm[pipe.model_label].v_min,
        session_id=session_id,
        model=model.adapter,
        feature_schema=model.stream.schema,
        feature_window_n=model.manifest["N"],
        norm_stats=model.stats,
        feature_records=reference_features,
        dropped_by_frame=drops,
        delay=DelayPolicy("per_frame", per_frame_s=delays),
        nominal_dt_s=pipe.nominal_dt_s,
    )
    features = [hf.features for r in results for hf in r.hands.values()]
    predictions = [hf.model_prediction for r in results for hf in r.hands.values() if hf.model_prediction]
    candidates = [hf.model_candidate for r in results for hf in r.hands.values() if hf.model_candidate]
    commits = [c for r in results for c in r.commits if c.arm == pipe.model_label]
    # Global geometry IDs include A/B candidates in live mode. Verify the links before canonical comparison.
    live_by_id = {c.candidate_id: c for c in candidates}
    offline_by_id = {c.candidate_id: c for c in offline.candidates}
    links = compare_records(
        [live_by_id[c.candidate_id] for c in commits],
        [offline_by_id[c.candidate_id] for c in offline.committed],
        ignored=("candidate_id", "t_candidate"),
    )
    comparisons = {
        "features": compare_records(features, reference_features, atol=1e-10, rtol=1e-10),
        "predictions": compare_records(predictions, offline.predictions, ignored=("t_inference_done",)),
        "candidates": compare_records(
            candidates, offline.candidates, ignored=("candidate_id", "t_candidate")
        ),
        "commits": compare_records(commits, offline.committed, ignored=("candidate_id",)),
        "commit_candidate_links": links,
    }
    for name, rows in (
        ("kinematic-features", features),
        ("trajectory-prediction", predictions),
        ("strike-candidate", candidates),
        ("committed-strike", commits),
    ):
        for record in rows:
            validate(name, record.to_dict())
    for result in results:
        for record in result.timing:
            validate("timing-record", record.to_dict())
    return {
        "session_id": session_id,
        "passed": True,
        "frames": len(results),
        "model_id": model.model_id,
        "model_training_kind": model.manifest["source_kind"],
        "comparisons": comparisons,
        "delta_proc_s": delays,
        "empty_prediction_set": not predictions,
        "empty_commit_set": not commits,
        "comparison_scope": "raw perception -> live tracking; fresh Phase 09 model/features/geometry/commit",
        "clock_exclusions": ["t_inference_done", "t_candidate"],
        "candidate_ids": "allocation order differs; committed candidate links independently checked",
    }, results


def begin_evidence():
    return execution(), source_hashes()


def save_evidence(directory, name, report, *, started):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    context, initial = started
    final = source_hashes()
    unchanged = initial == final
    write_json(
        directory / name,
        {**context, **report, "finished_at": wall_clock_iso(), "source_unchanged_during_run": unchanged},
    )
    write_json(directory / "source-hashes-start.json", initial)
    write_json(directory / "source-hashes.json", final)
    if not unchanged:
        raise RuntimeError("source changed during evidence run; rerun on stable source")
    return directory / name


def read_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan["source_kind"] not in ("DEV_CAPTURE", "PARTICIPANT"):
        raise ValueError("raw parity plan must declare DEV_CAPTURE or PARTICIPANT")
    if not plan["sessions"] or len({s["id"] for s in plan["sessions"]}) != len(plan["sessions"]):
        raise ValueError("nonempty unique session roster required")
    if plan["source_kind"] == "PARTICIPANT":
        split = json.loads(Path(plan["fold_manifest"]).read_text(encoding="utf-8"))
        fold = next(f for f in split["folds"] if f["fold"] == plan["fold"])
        expected = set(fold["train_sessions"]) | set(fold["val_sessions"])
        declared = {s["id"] for s in plan["sessions"] if s["kind"] == "PARTICIPANT"}
        if expected != declared or not any(s["kind"] == "DEV_CAPTURE" for s in plan["sessions"]):
            raise ValueError("parity roster must include every session in the fold plus developer sessions")
        for session in plan["sessions"]:
            if session["kind"] == "PARTICIPANT":
                meta = json.loads((Path(session["path"]) / "metadata.json").read_text(encoding="utf-8"))
                validate("session-metadata", meta)
                if meta["session_kind"] != "PARTICIPANT" or meta["session_id"] != session["id"]:
                    raise ValueError("participant session provenance mismatch")
    elif any(s["kind"] != "DEV_CAPTURE" for s in plan["sessions"]):
        raise ValueError("developer-only plan contains a non-developer session")
    return plan
