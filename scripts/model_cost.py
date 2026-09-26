"""Paired CPU cost/export-parity screening of the pinned model; no training or deployment.

Creates separately hashed experimental packages for subsequent raw/harness regression.
Quantization is never adopted solely because this small numerical screen passes.
"""

import argparse
import copy
import json
import time
from pathlib import Path

import torch
import yaml
from _p10 import write_json
from _p16 import distribution, evidence

from spacedrums.models.temporal.config import TemporalConfig
from spacedrums.models.temporal.data import read_samples, sha
from spacedrums.models.temporal.export import load_model
from spacedrums.models.temporal.train import diagnostics, predictions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--val-samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calls", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    if min(args.calls, args.repeats) < 1:
        parser.error("positive counts required")
    torch.set_num_threads(1)
    with evidence(args.config, args.output, "model-cost", "16.6") as (run, cfg):
        original = Path(cfg["anticipator"]["model"]["path"])
        model, manifest = load_model(original)
        if sha(args.val_samples) != manifest["val_samples_hash"]:
            raise ValueError("only pinned validation archive may be opened")
        sample = read_samples(
            args.val_samples, TemporalConfig(**manifest["config"]), aux_horizon_s=manifest["aux_horizon_s"]
        )
        eager, _ = load_model(original, exported=False)
        models = {
            "float": model,
            "frozen": torch.jit.freeze(copy.deepcopy(model).eval()),
            "int8": torch.jit.script(
                torch.ao.quantization.quantize_dynamic(
                    eager.eval(), {torch.nn.GRU, torch.nn.Linear}, dtype=torch.qint8
                )
            ),
        }
        rows, outputs, latencies = {}, {}, {k: [] for k in models}
        with torch.inference_mode():
            for name, candidate in models.items():
                outputs[name] = predictions(candidate, sample)[0]
                if name != "float":
                    directory = run.dir / name
                    directory.mkdir()
                    candidate.save(str(directory / "export.pt"))
                    m = {
                        **manifest,
                        "export_hash": sha(directory / "export.pt"),
                        "phase16_candidate": name,
                        "deployment_selected": False,
                    }
                    write_json(directory / "manifest.json", m)
                    c = copy.deepcopy(cfg.data)
                    c["anticipator"]["model"].update(
                        path=directory.as_posix(),
                        hash=m["export_hash"],
                        manifest_hash=sha(directory / "manifest.json"),
                    )
                    # Preserve ordered grip-weight accumulation in the original configuration.
                    # Sorting YAML keys can perturb exact upstream float records independently
                    # of the model candidate, confounding the paired regression.
                    (directory / "config.yaml").write_text(
                        yaml.safe_dump(c, sort_keys=False), encoding="utf-8"
                    )
                    # Verify serialization does not hide a different candidate.
                    reloaded, _ = load_model(directory)
                    torch.testing.assert_close(
                        predictions(reloaded, sample)[0], outputs[name], atol=0, rtol=0
                    )
                x, mask = sample["tensors"]["x"], sample["tensors"]["mask"]
                for i in range(20):
                    candidate(x[i : i + 1], mask[i : i + 1])
            names = list(models)
            for repeat in range(args.repeats):
                for name in names[repeat:] + names[:repeat]:
                    values = []
                    for i in range(args.calls):
                        j = i % sample["count"]
                        start = time.perf_counter()
                        models[name](x[j : j + 1], mask[j : j + 1])
                        values.append(time.perf_counter() - start)
                    latencies[name].append(values)
            for name in models:
                error = (outputs[name] - outputs["float"]).abs()
                parity = bool(torch.all(error <= 1e-6 + 1e-5 * outputs["float"].abs()))
                rows[name] = {
                    "latency": distribution([t for r in latencies[name] for t in r]),
                    "per_repeat": [distribution(r) for r in latencies[name]],
                    "raw_s": latencies[name],
                    "max_abs_output_delta": float(error.max()),
                    "export_tolerance_passed": parity,
                    "metrics": diagnostics(outputs[name], sample),
                    "retained": False,
                }
        write_json(
            run.dir / "model-cost.json",
            {
                "model_id": manifest["model_id"],
                "model_source_kind": manifest["source_kind"],
                "shipped_model": "PENDING owner selection",
                "validation_samples_hash": sha(args.val_samples),
                "calls_per_repeat": args.calls,
                "repeats": args.repeats,
                "warmup": 20,
                "threads": 1,
                "variants": rows,
                "adoption": "requires full raw/harness regression and end-to-end gain",
            },
        )
        print(
            json.dumps(
                {
                    k: {
                        "p95_ms": v["latency"]["p95_ms"],
                        "max_abs_delta": v["max_abs_output_delta"],
                        "parity": v["export_tolerance_passed"],
                    }
                    for k, v in rows.items()
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
