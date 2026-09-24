"""TorchScript export, fold-sample numerical parity, and CPU batch-one timings."""

import json
from pathlib import Path

import numpy as np
import torch

from spacedrums.timing import now

from .config import TemporalConfig, build_model
from .data import sha
from .gru import BoundedGRUState


def load_model(directory, *, exported=True):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    config = TemporalConfig(**manifest["config"])
    if config.config_hash != manifest["config_hash"]:
        raise ValueError("configuration hash mismatch")
    expected = {
        "N": config.n,
        "K": config.k,
        "F": config.features,
        "dt_step": config.dt_step,
        "family": config.family,
    }
    if any(manifest[key] != value for key, value in expected.items()):
        raise ValueError("manifest dimensions differ from hashed configuration")
    filename, key = ("export.pt", "export_hash") if exported else ("checkpoint.pt", "checkpoint_hash")
    if sha(directory / filename) != manifest[key]:
        raise ValueError("model content hash mismatch")
    if exported:
        model = torch.jit.load(str(directory / filename), map_location="cpu")
    else:
        model = build_model(config)
        model.load_state_dict(torch.load(directory / filename, weights_only=True, map_location="cpu"))
    return model.eval(), manifest


@torch.inference_mode()
def export_model(model, directory, sample, *, atol=1e-6, rtol=1e-5):
    directory = Path(directory)
    scripted = torch.jit.script(model.eval())
    scripted.save(str(directory / "export.pt"))
    loaded = torch.jit.load(str(directory / "export.pt")).eval()
    t, max_error, comparisons = sample["tensors"], 0.0, 0
    for batch_size in (1, 31):
        for i in range(0, sample["count"], batch_size):
            args = (t["x"][i : i + batch_size], t["mask"][i : i + batch_size])
            eager, exported = model(*args), loaded(*args)
            for a, b in zip(eager, exported, strict=True):
                torch.testing.assert_close(a, b, atol=atol, rtol=rtol)
                max_error = max(max_error, float((a - b).abs().max()))
            comparisons += len(args[0])
    report = {
        "passed": True,
        "atol": atol,
        "rtol": rtol,
        "max_abs_error": max_error,
        "comparisons": comparisons,
        "samples_hash": sample["hash"],
        "torch_version": str(torch.__version__),
    }
    (directory / "parity.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        export_format="TorchScript", export_hash=sha(directory / "export.pt"), parity_report="parity.json"
    )
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return report


@torch.inference_mode()
def latency(model, sample, *, family, calls=300, warmup=30, threads=1):
    if calls < 1 or warmup < 0 or threads < 1:
        raise ValueError("invalid benchmark counts")
    torch.set_num_threads(threads)
    model.eval()
    x, mask = sample["tensors"]["x"], sample["tensors"]["mask"]
    rows = {}
    functions = {"windowed": lambda i: model(x[i : i + 1], mask[i : i + 1])}
    cache = BoundedGRUState(model) if family == "gru" else None
    if cache:
        functions["bounded_stateful"] = lambda i: cache(x[i], mask[i])
    for name, fn in functions.items():
        for i in range(warmup):
            fn(i % len(x))
        timings = []
        for i in range(calls):
            start = now()
            fn(i % len(x))
            timings.append((now() - start) * 1000)
        rows[name] = {
            "p50_ms": float(np.percentile(timings, 50)),
            "p95_ms": float(np.percentile(timings, 95)),
            "p99_ms": float(np.percentile(timings, 99)),
            "raw_ms": timings,
        }
    if cache:
        rows["cache_counts"] = {
            "rebuilds_including_warmup": cache.rebuilds,
            "incremental_steps_including_warmup": cache.incremental_steps,
        }
    return {
        "method": "spacedrums.timing.now; batch=1; CPU; inputs prepared; I/O/feature extraction excluded",
        "calls": calls,
        "warmup": warmup,
        "threads": threads,
        "torch_version": str(torch.__version__),
        "samples_hash": sample["hash"],
        "results": rows,
    }
