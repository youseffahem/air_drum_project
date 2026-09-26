"""Batch-one CPU latency and memory for Phase 12 (Task 12.5 feasibility gate; go/no-go CPU criterion).

--feasibility: randomly initialised Phase 10 GRU/TCN and the declared Tiny Transformer at the
development size, TorchScript, batch 1, one thread, interleaved blocks in one process, measured
BEFORE any TT training. Verdict FEASIBLE iff TT p95 <= F x max(GRU p95, TCN p95) (F = 3, declared).
Larger TT sizes are timed for information only and never change the verdict.

--runs: one fold-0/seed-10 model per variant and family from completed grid runs; the
inference-to-candidate path (forward, decoding, deterministic geometry, and the crossing probability
where a variant uses it) timed on validation windows whose point trajectory yields a candidate;
working set in a fresh subprocess. Run alone on an idle machine. DEVELOPMENT CPU COMPUTE on HW-01:
cost depends on the architecture, not on the synthetic weights.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from _p10 import hardware, provenance, source_hashes, write_json
from _p11 import V_MIN
from _p12 import (
    CROSSING,
    DEV,
    EXPLORATORY_PROBABILISTIC,
    F_CPU,
    NOT_CODEX,
    PROBABILISTIC,
    ext_config,
    load_any,
    load_run_rows,
)
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.geometry import GeometryEngine, ZoneRegistry
from spacedrums.geometry.probabilistic import common_draws, intersect_prob
from spacedrums.models.temporal import TemporalConfig, build_model
from spacedrums.models.temporal.data import read_samples
from spacedrums.models.temporal.ext import build_extension_model
from spacedrums.models.temporal.ext.adapter import decode_extension, extension_config
from spacedrums.models.temporal.ext.long_horizon import select_grid
from spacedrums.models.temporal.ext.uncertainty import member_rows
from spacedrums.timing import now

ROOT = Path(__file__).resolve().parents[1]
INFORMATIONAL_TT = {"tt-w32-l2-h4": {"hidden": 32, "attention_heads": 4, "feedforward": 64, "layers": 2}}


def _percentiles(values):
    return {
        "calls": len(values),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
    }


def interleaved(functions, *, blocks, calls, warmup):
    """Time each named zero-argument-per-index function in interleaved blocks (drift spread)."""
    raw = {name: [] for name in functions}
    with torch.inference_mode():
        for block in range(blocks):
            for name, (fn, count) in functions.items():
                for i in range(warmup if block == 0 else 10):
                    fn(i % count)
                for i in range(calls):
                    start = now()
                    fn((block * calls + i) % count)
                    raw[name].append((now() - start) * 1000)
    return raw


def feasibility(args, run, context):
    torch.set_num_threads(1)
    torch.manual_seed(1212)
    features = 56
    x = torch.randn(64, DEV["n"], features)
    mask = torch.rand(64, DEV["n"], features) > 0.2
    models = {
        "gru": build_model(TemporalConfig("gru", features, n=DEV["n"], k=4, hidden=DEV["hidden"])),
        "tcn": build_model(TemporalConfig("tcn", features, n=DEV["n"], k=4, hidden=DEV["hidden"])),
        "tt": build_extension_model(ext_config("e3-tt", "tt", features=features)),
    }
    for name, overrides in INFORMATIONAL_TT.items():
        config = ext_config("e3-tt", "tt", features=features)
        models[name] = build_extension_model(type(config).from_dict({**config.to_dict(), **overrides}))
    scripted = {name: torch.jit.script(model.eval()) for name, model in models.items()}
    functions = {
        name: (lambda i, m=model: m(x[i : i + 1], mask[i : i + 1]), len(x))
        for name, model in scripted.items()
    }
    raw = interleaved(functions, blocks=args.blocks, calls=args.calls // args.blocks, warmup=100)
    rows = {
        name: {
            **_percentiles(values),
            "parameter_count": sum(p.numel() for p in models[name].parameters()),
            "informational_only": name in INFORMATIONAL_TT,
        }
        for name, values in raw.items()
    }
    budget = F_CPU * max(rows["gru"]["p95"], rows["tcn"]["p95"])
    verdict = "FEASIBLE" if rows["tt"]["p95"] <= budget else "INFEASIBLE"
    report = {
        "verdict": verdict,
        "rule": f"TT p95 <= F x max(GRU p95, TCN p95), F = {F_CPU} (docs/experiments/phase-12-prereg.md)",
        "budget_p95_ms": budget,
        "results_ms": rows,
        "inputs": "random normal x [1, N=8, F=56], random 80 % mask (seed 1212); random-initialised weights",
        "method": "TorchScript; batch 1; 1 thread; spacedrums.timing.now; "
        f"{args.blocks} interleaved blocks x {args.calls // args.blocks} calls, 100 warm-up calls first",
        "evidence": "DEVELOPMENT CPU COMPUTE on HW-01; measured before any Phase 12 TT training",
    }
    write_json(run.dir / "feasibility.json", report)
    write_json(run.dir / "raw.json", raw)
    print(json.dumps({k: report[k] for k in ("verdict", "budget_p95_ms")}), flush=True)
    return {"verdict": verdict, "budget_p95_ms": budget, "tt_p95_ms": rows["tt"]["p95"]}


def _pick(rows, variant, family):
    for row in rows:
        if row["variant"] == variant and row["family"] == family and row["fold"] == 0:
            if row["seed"] in (10, "ensemble"):
                return row
    return None


def _candidates(entry):
    """Validation windows whose point trajectory yields a deterministic geometry candidate."""
    with torch.inference_mode():
        found = [i for i in range(entry["sample"]["count"]) if entry["path"](i, gate=False) is not None]
    if not found:
        raise ValueError(f"no candidate frame for {entry['name']}")
    return found


def build_entry(name, variant, row, cfg):
    registry = ZoneRegistry.from_config(cfg["zones"])
    engine = GeometryEngine(registry, v_min=V_MIN, session_id="p12-latency")
    draws = common_draws(CROSSING["samples"], seed=CROSSING["seed"])
    dirs = row.get("model_dirs") or [row["model_dir"]]
    loaded = [load_any(d) for d in dirs]
    models, manifests = [m for m, _ in loaded], [m for _, m in loaded]
    config = extension_config(manifests[0])
    samples = Path(row["fold_dir"]) / "samples.val.npz"
    sample = select_grid(read_samples(samples, config.data_view), config)
    x, mask = sample["tensors"]["x"], sample["tensors"]["mask"]
    ensemble = len(models) > 1
    a_max = row.get("a_max")
    gate = variant in PROBABILISTIC + EXPLORATORY_PROBABILISTIC

    def forward(i):
        return [model(x[i : i + 1], mask[i : i + 1]) for model in models]

    def path(i, gate=gate):
        outputs = forward(i)
        meta, anchor = sample["meta"][i], tuple(float(v) for v in sample["anchor"][i])
        track = SimpleNamespace(
            frame_id=meta["frame_id"], t_capture=meta["t_i"], hand_id=meta["hand_id"], tip_filtered=anchor
        )
        rows = kind = None
        if ensemble:
            members = np.stack([o[0][0].numpy() for o in outputs])
            point, aux = members.mean(0), np.zeros(1)
            rows, kind = member_rows(point, members), "members_xy"
        else:
            point, aux = outputs[0][0][0].numpy(), outputs[0][1][0].numpy()
        prediction = decode_extension(
            track, point, aux, config, anticipator_id="p12-latency", model_hash=None, a_max=a_max,
            uncertainty=rows, kind=kind,
        )  # fmt: skip
        candidate = engine.intersect_prediction(
            prediction, current_position=anchor, source="MODEL", t_candidate=meta["t_i"]
        )
        if gate and candidate is not None:
            distribution = intersect_prob(registry, prediction, anchor, v_min=V_MIN, draws=draws)
            return candidate, distribution.zone_probability(candidate.zone_id)
        return candidate

    return {
        "name": name,
        "variant": variant,
        "family": manifests[0]["family"],
        "model_dirs": dirs,
        "forward": forward,
        "path": path,
        "sample": sample,
        "samples_path": str(samples),
        "parameter_count": sum(m["parameter_count"] for m in manifests),
        "export_bytes": sum((Path(d) / "export.pt").stat().st_size for d in dirs),
        "models": len(models),
    }


def working_set_probe(model_dirs, samples):
    from latency_mt import working_set

    torch.set_num_threads(1)
    before = working_set()
    loaded = [load_any(d) for d in model_dirs]
    after_load = working_set()
    config = extension_config(loaded[0][1])
    sample = read_samples(samples, config.data_view)
    x, mask = sample["tensors"]["x"], sample["tensors"]["mask"]
    with torch.inference_mode():
        for i in range(200):
            for model, _ in loaded:
                model(x[i % len(x) : i % len(x) + 1], mask[i % len(x) : i % len(x) + 1])
    after = working_set()
    print(
        json.dumps(
            {
                "before_load": before[0],
                "after_load": after_load[0],
                "after_inference": after[0],
                "peak": after[1],
                "load_delta": None if before[0] is None else after_load[0] - before[0],
            }
        )
    )


def trained(args, run, context):
    torch.set_num_threads(1)
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    rows = []
    for run_dir in args.runs:
        _, run_rows = load_run_rows(run_dir)
        rows.extend(run_rows)
    entries = {}
    for variant in sorted({r["variant"] for r in rows}):
        for family in ("gru", "tcn", "tt"):
            row = _pick(rows, variant, family)
            if row is not None:
                name = f"{variant}/{family}"
                entries[name] = build_entry(name, variant, row, cfg)
    candidates = {name: _candidates(entry) for name, entry in entries.items()}
    per_block = args.calls // args.blocks
    forward_raw = interleaved(
        {name: (e["forward"], e["sample"]["count"]) for name, e in entries.items()},
        blocks=args.blocks,
        calls=per_block,
        warmup=100,
    )
    path_raw = interleaved(
        {
            name: (lambda i, e=e, c=candidates[name]: e["path"](c[i]), len(candidates[name]))
            for name, e in entries.items()
        },
        blocks=args.blocks,
        calls=per_block,
        warmup=20,
    )
    report = {}
    for name, entry in entries.items():
        probe = subprocess.run(
            [
                sys.executable,
                __file__,
                "--memory-probe",
                *entry["model_dirs"],
                "--samples",
                entry["samples_path"],
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        report[name] = {
            "variant": entry["variant"],
            "family": entry["family"],
            "models": entry["models"],
            "model_dirs": entry["model_dirs"],
            "parameter_count": entry["parameter_count"],
            "export_bytes": entry["export_bytes"],
            "candidate_frames": len(candidates[name]),
            "forward_ms": _percentiles(forward_raw[name]),
            "path_ms": _percentiles(path_raw[name]),
            "memory_bytes": json.loads(probe.stdout.strip().splitlines()[-1]),
        }
    for entry in report.values():
        references = [
            report.get(f"ref/{f}")
            for f in (("gru", "tcn") if entry["family"] == "tt" else (entry["family"],))
        ]
        references = [r for r in references if r is not None]
        if not references:
            entry["cpu_rule"] = None
            continue
        budget = F_CPU * max(r["path_ms"]["p95"] for r in references)
        entry["cpu_rule"] = {
            "budget_p95_ms": budget,
            "path_p95_ms": entry["path_ms"]["p95"],
            "ratio_to_reference": entry["path_ms"]["p95"] / max(r["path_ms"]["p95"] for r in references),
            "within_budget": entry["path_ms"]["p95"] <= budget,
            "rule": f"path p95 <= {F_CPU} x reference path p95 (same family; TT vs max of GRU/TCN)",
        }
    report["method"] = (
        "spacedrums.timing.now; batch 1; 1 thread; TorchScript exports; forward on all validation windows; "
        "path = forward + decode + deterministic geometry (+ crossing probability, S=32, where declared) on "
        f"candidate windows; {args.blocks} interleaved blocks x {per_block} calls per entry; working set via "
        "GetProcessMemoryInfo in a fresh subprocess (includes the Python/PyTorch runtime)"
    )
    write_json(run.dir / "latency-memory.json", report)
    write_json(run.dir / "raw.json", {"forward": forward_raw, "path": path_raw})
    return {"entries": sorted(entries)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--feasibility", action="store_true")
    mode.add_argument("--runs", type=Path, nargs="+")
    mode.add_argument("--memory-probe", type=Path, nargs="+", help=argparse.SUPPRESS)
    ap.add_argument("--samples", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--calls", type=int, default=1000)
    ap.add_argument("--blocks", type=int, default=10)
    ap.add_argument("--output", type=Path, default=ROOT / "experiments/phase-12")
    args = ap.parse_args()
    if args.memory_probe:
        return working_set_probe(args.memory_probe, args.samples)
    if not (args.feasibility or args.runs) or args.calls % args.blocks:
        ap.error("--feasibility or --runs required; calls must be a multiple of blocks")
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    with RunLog(
        phase="12",
        task="12.5" if args.feasibility else "12.2",
        slug="tt-feasibility" if args.feasibility else "ext-latency-memory",
        config=cfg,
        experiments_dir=args.output,
        description="Batch-one CPU latency (development compute); "
        + (
            "E3 feasibility gate before training" if args.feasibility else "extension path latency and memory"
        ),
    ) as run:
        context = {**provenance(), "hardware": hardware(), **NOT_CODEX}
        write_json(run.dir / "execution.json", {**context, "input_runs": [str(r) for r in args.runs or []]})
        write_json(run.dir / "source-hashes.json", source_hashes())
        summary = feasibility(args, run, context) if args.feasibility else trained(args, run, context)
        for path in sorted(run.dir.iterdir()):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(summary, notes="DEVELOPMENT CPU COMPUTE on HW-01; not a deployment budget.")
        print(run.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
