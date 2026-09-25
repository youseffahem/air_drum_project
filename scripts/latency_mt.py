"""Batch-one CPU latency, parameters and memory: multi-task versus single-task (Task 11.8).

Pairs come from one completed grid run with identical fold/seed/family: trajectory-only (the
Phase 10 single-task model, bit-identical training) and the all-heads C-MT model. Timings
interleave the models in blocks within one process to spread drift; each model's working set is
measured in a fresh subprocess. Run alone on an idle machine. DEVELOPMENT CPU COMPUTE only:
inference cost depends on architecture, not on the synthetic weights, but the host is HW-01.
"""

import argparse
import ctypes
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from _p10 import hardware, provenance, write_json
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.models.temporal.config import MultiTaskConfig
from spacedrums.models.temporal.data import read_samples
from spacedrums.models.temporal.export import latency, load_mt_model


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set():
    """(current, peak) working set bytes of this process; Windows only, else (None, None)."""
    if sys.platform != "win32":
        return None, None
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = ctypes.c_void_p
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters), ctypes.c_ulong]
    if not query(process(), ctypes.byref(counters), counters.cb):
        return None, None
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def memory_probe(model_dir, samples, calls):
    import torch

    torch.set_num_threads(1)
    before = working_set()
    model, manifest = load_mt_model(model_dir)
    loaded = working_set()
    sample = read_samples(samples, MultiTaskConfig.from_dict(manifest["mt_config"]).base)
    x, mask = sample["tensors"]["x"], sample["tensors"]["mask"]
    with torch.inference_mode():
        for i in range(calls):
            model(x[i % len(x) : i % len(x) + 1], mask[i % len(x) : i % len(x) + 1])
    after = working_set()
    print(
        json.dumps(
            {
                "before_load": before[0],
                "after_load": loaded[0],
                "after_inference": after[0],
                "peak": after[1],
                "load_delta": None if before[0] is None else loaded[0] - before[0],
                "inference_delta": None if loaded[0] is None else after[0] - loaded[0],
            }
        )
    )


def _pairs(run_dir, fold, seed, variants):
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    rows = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    found = {}
    for cell, row in zip(plan["cells"], rows, strict=True):
        if row["fold"] == fold and row["seed"] == seed and cell["variant"] in variants:
            found[(row["family"], cell["variant"])] = (cell, row)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path)
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--seed", type=int, default=10)
    ap.add_argument("--calls", type=int, default=1000)
    ap.add_argument("--blocks", type=int, default=10)
    ap.add_argument("--single", default="traj-only", help="single-task variant name in the run")
    ap.add_argument("--multi", default="all", help="multi-task variant name in the run")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--memory-probe", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--samples", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.memory_probe:
        return memory_probe(args.memory_probe, args.samples, 200)
    if not args.run or not args.output or args.calls % args.blocks:
        ap.error("--run and --output required; calls must be a multiple of blocks")
    cfg = load_config("configs/prototype.candidate.yaml")
    with RunLog(
        phase="11",
        task="11.8",
        slug="mt-latency-memory",
        config=cfg,
        experiments_dir=args.output,
        description="Batch-one CPU latency/parameters/memory, MT vs single-task (development compute)",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        context["codex_model"] = "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code"
        context["codex_reasoning_effort"] = "UNAVAILABLE to the agent; not asserted"
        write_json(run.dir / "execution.json", {**context, "input_run": str(args.run)})
        variants = (args.single, args.multi)
        pairs, report = _pairs(args.run, args.fold, args.seed, variants), {"pair": list(variants)}
        for family in ("gru", "tcn"):
            if any((family, v) not in pairs for v in variants):
                continue
            models = {}
            for variant in variants:
                cell, row = pairs[(family, variant)]
                model, manifest = load_mt_model(row["model_dir"])
                samples = Path(cell["fold_dir"]) / "samples.val.npz"
                sample = read_samples(samples, MultiTaskConfig.from_dict(manifest["mt_config"]).base)
                models[variant] = (model, manifest, sample, samples, Path(row["model_dir"]))
            raw = {v: {} for v in models}
            for block in range(args.blocks):
                for variant, (model, _, sample, _, _) in models.items():
                    bench = latency(
                        model,
                        sample,
                        family=family,
                        calls=args.calls // args.blocks,
                        warmup=100 if block == 0 else 10,
                        threads=1,
                    )
                    for mode, values in bench["results"].items():
                        if "raw_ms" in values:
                            raw[variant].setdefault(mode, []).extend(values["raw_ms"])
            report[family] = {}
            for variant, (_, manifest, _, samples, model_dir) in models.items():
                probe = subprocess.run(
                    [sys.executable, __file__, "--memory-probe", str(model_dir), "--samples", str(samples)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                export = model_dir / "export.pt"
                report[family][variant] = {
                    "model_id": manifest["model_id"],
                    "heads": manifest["heads"],
                    "parameter_count": manifest["parameter_count"],
                    "parameter_bytes": manifest["parameter_bytes"],
                    "export_bytes": export.stat().st_size,
                    "latency_ms": {
                        mode: {
                            "calls": len(values),
                            "p50": float(np.percentile(values, 50)),
                            "p95": float(np.percentile(values, 95)),
                            "p99": float(np.percentile(values, 99)),
                        }
                        for mode, values in raw[variant].items()
                    },
                    "memory_bytes": json.loads(probe.stdout.strip().splitlines()[-1]),
                }
            write_json(run.dir / f"raw-{family}.json", raw)
        report["method"] = (
            "spacedrums.timing.now via export.latency; batch=1; CPU; 1 thread; prepared inputs; blocks "
            f"interleaved {args.blocks}x{args.calls // args.blocks} calls per model; working set from "
            "GetProcessMemoryInfo in a fresh subprocess (includes the Python/PyTorch runtime)"
        )
        write_json(run.dir / "latency-memory.json", report)
        for path in sorted(run.dir.iterdir()):
            if path.is_file() and path.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(path, "other")
        run.finish(
            {"families": [k for k in report if k in ("gru", "tcn")]},
            notes="DEVELOPMENT CPU COMPUTE on HW-01.",
        )
        print(run.dir)


if __name__ == "__main__":
    main()
