"""Phase 18 orchestration helpers: evidence runs, arms built from a frozen-inputs lock, session evaluation.

Composes library code only. Geometry, commit, matching and metrics are the unchanged Phase 04/05/09
implementations; ``spacedrums.live_eval`` adds the confirmatory analysis layer. The rehearsal
constants below are **SYNTHETIC development values** for exercising the runners on the Phase 11
kinematic fixture. They are never owner budgets, operating points or a participant result
(pre-registration §11).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from _p10 import provenance, source_hashes, write_json
from _runlog import RunLog, git_dirty, git_sha

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.eval.replay import DelayPolicy, ReplayResult, replay
from spacedrums.eval.report import evaluate_session
from spacedrums.features.normalize import NormStats
from spacedrums.geometry import ZoneRegistry
from spacedrums.live_eval import offline
from spacedrums.live_eval.prereg import file_digest
from spacedrums.prediction import RuleSettings
from spacedrums.timing import wall_clock_iso

ROOT = Path(__file__).resolve().parents[1]
PREREG_DOC = "docs/experiments/phase-18-prereg.md"
PREREG_PATH = ROOT / PREREG_DOC
RECORD_PATH = ROOT / "docs/experiments/phase-18-prereg.hashes.json"
LEDGER_PATH = ROOT / "docs/experiments/phase-18-confirmatory-ledger.jsonl"
OUTPUT = ROOT / "experiments" / "phase-18"
RULE_CONFIG = ROOT / "configs" / "prototype.candidate.yaml"
LIVE_CONFIG = ROOT / "configs" / "live.arm-C.candidate.yaml"
PIPELINE_PACKAGES = ("eval", "live_eval", "geometry", "commit", "prediction", "models", "features")

# SYNTHETIC rehearsal constants (declared in every rehearsal lock's notes; not owner values).
REHEARSAL = {
    "identities": 12,
    "seconds": 24.0,
    "n": 8,
    "k": 4,
    "hidden": 16,
    "epochs": 8,
    "train_seed": 10,
    "gbdt_seed": 9,
    "fold": 0,
    "delta_proc_s": 0.030,
    "w_s": 0.05,
    "fp_budget_per_min": 30.0,
    "fn_ceiling": 0.6,
    "delta_audio_s": 0.030,
    "delta_lead_s": 0.005,
    "cpu_p95_ms": 50.0,
}
REHEARSAL_NOTE = (
    "SYNTHETIC rehearsal lock on the Phase 11 kinematic fixture: development constants (W = the 50 ms "
    "candidate, Delta_proc 30 ms, FP 30/min, FN 0.6, delta_audio 30 ms, delta_lead 5 ms, CPU 50 ms), "
    "fold-0 models and validation picks with eval.selection.select_point (FP / FN budgets only); "
    "machinery only, "
    "never evidence"
)
CURVE_TAUS = (0.02, 0.05, 0.10, 0.15, 0.20)
CURVE_PROBABILITIES = (0.3, 0.5, 0.7)


# ----------------------------------------------------------------------------- provenance


def add_executor_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--executor-model", default="UNVERIFIED", help="who runs this (recorded, never inferred)")
    ap.add_argument("--executor-effort", default="UNVERIFIED")


def execution(args: argparse.Namespace) -> dict[str, Any]:
    p = provenance()
    p["codex_model"] = args.executor_model
    p["codex_reasoning_effort"] = args.executor_effort
    p["executor_note"] = "executor fields are command-line arguments (Phase 17 rule); never inferred"
    return p


def pipeline_sources() -> dict[str, str]:
    """Digest of every pipeline source the replay imports (the lock freezes these)."""
    return {
        "configs/prototype.candidate.yaml": file_digest(RULE_CONFIG),
        **{
            p.relative_to(ROOT).as_posix(): file_digest(p)
            for pkg in PIPELINE_PACKAGES
            for p in sorted((ROOT / "src" / "spacedrums" / pkg).rglob("*.py"))
        },
    }


def harness_sources() -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): file_digest(p)
        for p in sorted((ROOT / "src" / "spacedrums" / "eval").glob("*.py"))
    }


@contextmanager
def evidence(args, *, slug: str, task: str, description: str, output: Path = OUTPUT, config_path=RULE_CONFIG):
    cfg = load_config(config_path)
    with RunLog(
        phase="18", task=task, slug=slug, config=cfg, experiments_dir=Path(output), description=description
    ) as run:
        initial = source_hashes()
        write_json(run.dir / "execution.json", execution(args))
        write_json(run.dir / "source-hashes-start.json", initial)
        yield run, cfg
        final = source_hashes()
        audit = {
            "source_unchanged": initial == final,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "finished_at": wall_clock_iso(),
        }
        write_json(run.dir / "audit.json", audit)
        if initial != final:
            raise RuntimeError("source changed during measurement")
        for p in sorted(run.dir.rglob("*")):
            if p.is_file() and p.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(p, "other")
        run.finish(audit, status="COMPLETED", notes="Dirty-tree values are development diagnostics only.")
        print(f"EVIDENCE: {run.dir}", flush=True)


# ----------------------------------------------------------------------------- arms


@dataclass
class Arm:
    """One locked arm: replay arm id, controls, rule settings, loaded model and fold statistics."""

    spec: dict[str, Any]
    cfg: Any
    registry: ZoneRegistry
    rule: RuleSettings | None = None
    model_fn: Any = None
    stats: Any = None
    window_n: int = 8
    gate_factory: Callable[[], Any] | None = None
    loaded: dict[str, Any] = field(default_factory=dict)

    @property
    def arm_id(self) -> str:
        return self.spec["arm_id"]

    @property
    def is_model(self) -> bool:
        return self.spec["replay_arm"].startswith("MODEL:")

    def settings(self, controls: Mapping[str, Any] | None = None) -> tuple[CommitSettings, float]:
        c = dict(controls or self.spec["controls"])
        v_min = float(c.pop("v_min"))
        return replace(CommitSettings.from_config(self.cfg), **c), v_min

    def run(
        self,
        tracks: Sequence[Any],
        *,
        session_id: str,
        schema: Any,
        delay_s: float,
        controls: Mapping[str, Any] | None = None,
        feature_records: Sequence[Any] | None = None,
    ) -> ReplayResult:
        commit, v_min = self.settings(controls)
        reset = getattr(self.model_fn, "reset", None)
        if reset is not None:
            reset()
        return replay(
            tracks,
            arm=self.spec["replay_arm"],
            registry=self.registry,
            commit_settings=commit,
            v_min=v_min,
            session_id=session_id,
            delay=DelayPolicy("fixed", delay_s) if delay_s else DelayPolicy(),
            rule_settings=self.rule,
            model=self.model_fn if self.is_model else None,
            feature_schema=schema if self.is_model else None,
            feature_window_n=self.window_n,
            norm_stats=self.stats if self.is_model else None,
            feature_records=feature_records if self.is_model else None,
            candidate_gate=self.gate_factory() if self.gate_factory else None,
        )


def _check_digest(path: Path, expected: str | None, what: str) -> None:
    if expected is not None and file_digest(path) != expected:
        raise ValueError(f"{what}: {path} does not match its locked digest")


def build_arm(spec: Mapping[str, Any], cfg: Any, *, dataset: Mapping[str, Any], schema: Any) -> Arm:
    arm = Arm(dict(spec), cfg, ZoneRegistry.from_config(cfg["zones"]))
    if spec["replay_arm"] == "B":
        arm.rule = replace(RuleSettings.from_config(cfg), **(spec["rule"] or {}))
    model = spec.get("model")
    if not model:
        return arm
    path = ROOT / model["path"]
    _check_digest(path / "manifest.json", model["manifest_sha256"], f"arm {spec['arm_id']} manifest")
    if model.get("export_sha256"):
        _check_digest(path / "export.pt", model["export_sha256"], f"arm {spec['arm_id']} export")
    stats_path = ROOT / model["norm_stats_path"]
    _check_digest(stats_path, model.get("norm_stats_sha256"), f"arm {spec['arm_id']} normalization")
    arm.stats = NormStats.read(
        stats_path,
        fold=model["fold"],
        dataset_version=dataset["version"],
        split_hash=dataset["split_sha256"],
        dataset_hash=dataset["manifest_sha256"],
        schema=schema,
    )
    if model["kind"] == "gbdt":
        from spacedrums.models.gbdt.adapter import GBDTAdapter
        from spacedrums.models.gbdt.predict import GBDTPredictor

        predictor = GBDTPredictor(path)
        arm.model_fn = GBDTAdapter(predictor, mode=model["mode"])
        arm.window_n = int(predictor.manifest["feature_shape"][0])
        arm.loaded = {"model_hash": predictor.model_hash}
    elif model["kind"] == "temporal":
        import torch

        from spacedrums.models.temporal.adapter import TemporalAnticipator
        from spacedrums.models.temporal.export import load_model

        torch.set_num_threads(1)  # deterministic batch-one replay (1 thread, as every Phase 10-12 grid)
        exported, manifest = load_model(path)
        arm.model_fn = TemporalAnticipator(exported, manifest)
        arm.window_n = int(manifest["N"])
        arm.loaded = {"model_hash": manifest.get("export_hash"), "family": manifest["family"]}
    else:
        from spacedrums.models.temporal.consistency import AuxGate, AuxHeadSettings
        from spacedrums.models.temporal.export import load_mt_model
        from spacedrums.models.temporal.mt_adapter import MultiTaskAnticipator

        exported, manifest = load_mt_model(path)
        arm.model_fn = MultiTaskAnticipator(exported, manifest)
        settings = AuxHeadSettings(**(model.get("aux_gate") or {}))
        arm.gate_factory = lambda: AuxGate(settings, manifest["heads"])
        arm.window_n = int(manifest["N"])
        arm.loaded = {"model_hash": manifest.get("export_hash"), "heads": manifest["heads"]}
    return arm


# ----------------------------------------------------------------------------- evaluation


def harness_inputs(session: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Labels / segments for the harness; SYNTHETIC fixture rows get the unit segment type."""
    labels, segments = session.labels, session.segments
    if session.table.source_kind == "SYNTHETIC":
        labels = [
            {
                **g,
                "qc_status": g.get("qc_status", "PENDING_REVIEW"),
                "review": g.get("review", {"reviewed": False}),
                "segment_type": g.get("segment_type", "SYNTHETIC_UNIT"),
                "t_start": g.get("t_start"),
                "t_end": g.get("t_end"),
            }
            for g in labels
        ]
        segments = [
            {**s, "type": s.get("type", "SYNTHETIC_UNIT"), "hands": s.get("hands", ["LEFT", "RIGHT"])}
            for s in segments
        ]
    return list(labels), list(segments)


def evaluate_arm_session(
    arm: Arm,
    session: Any,
    *,
    delay_s: float,
    w_s: float,
    controls: Mapping[str, Any] | None = None,
    s1: bool = False,
    keep_result: bool = False,
) -> dict[str, Any]:
    result = arm.run(
        session.tracks,
        session_id=session.table.session_id,
        schema=session.schema,
        delay_s=delay_s,
        controls=controls,
        feature_records=session.table.records,
    )
    rows = result.strike_rows(session.table.session_id, session.table.participant)
    labels, segments = harness_inputs(session)
    selftest = session.table.source_kind != "PARTICIPANT"
    out: dict[str, Any] = {
        "participant": session.table.participant,
        "session_id": session.table.session_id,
        "evaluation": evaluate_session(rows, labels, segments, w_s=w_s, include_unreviewed_selftest=selftest),
        "strikes": rows,
        "labels": labels,
        "n_predictions": len(result.predictions),
    }
    if s1:
        out["s1"] = {
            **out,
            "evaluation": offline.reference_time_evaluation(
                rows, labels, segments, w_s=w_s, include_unreviewed_selftest=selftest
            ),
        }
    if keep_result:
        out["result"] = result
    return out


def point(sessions: Sequence[Mapping[str, Any]], settings: Mapping[str, Any]) -> dict[str, Any]:
    """An achieved operating point (pooled over sessions) in the ``eval.selection`` format."""
    pooled = offline.pooled_metrics(sessions)
    return {
        "settings": dict(settings),
        "median_lead_s": pooled["lead_median_s"],
        "fp_per_min": pooled["fp_per_min"],
        "fn_rate": pooled["fn_rate"],
        "timing_mae_s": pooled["te_pred_mae_s"],
        "zone_accuracy": pooled["zone_accuracy"],
        "matched": pooled["matched"],
        "fp": pooled["fp"],
        "fn": pooled["fn"],
    }


def curve_grid(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Declared one-knob sweep around the frozen point (pre-registration §10, F1)."""
    base = dict(spec["controls"])
    if spec["replay_arm"] == "A":
        return [base]
    grid = [{**base, "tti_commit_s": tau} for tau in CURVE_TAUS]
    if float(base["p_commit"]) > 0:
        grid = [{**base, "p_commit": p} for p in CURVE_PROBABILITIES] + grid
    if base not in grid:
        grid.append(base)
    unique = []
    for g in grid:
        if g not in unique:
            unique.append(g)
    return unique


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "CURVE_PROBABILITIES",
    "CURVE_TAUS",
    "LEDGER_PATH",
    "OUTPUT",
    "PREREG_DOC",
    "PREREG_PATH",
    "RECORD_PATH",
    "REHEARSAL",
    "REHEARSAL_NOTE",
    "ROOT",
    "RULE_CONFIG",
    "Arm",
    "add_executor_args",
    "build_arm",
    "curve_grid",
    "evaluate_arm_session",
    "evidence",
    "execution",
    "harness_inputs",
    "harness_sources",
    "pipeline_sources",
    "point",
    "read_json",
]
