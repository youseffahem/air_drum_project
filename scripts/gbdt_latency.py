"""Measure batch-one, single-thread GBDT inference on the current CPU."""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np

from spacedrums.data.labels.schema import sha256_file
from spacedrums.models.gbdt.predict import GBDTPredictor
from spacedrums.models.gbdt.train import load_samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--calls", type=int, default=1000)
    args = parser.parse_args()
    if args.warmup < 0 or args.calls < 100:
        parser.error("warmup must be nonnegative and calls >= 100")
    predictor = GBDTPredictor(args.model_dir)
    sample = load_samples(args.samples)
    if (
        not len(sample["X"])
        or str(sample["feature_schema_hash"]) != predictor.manifest["feature_schema_hash"]
    ):
        raise ValueError("sample/model mismatch or empty sample")
    x, mask = sample["X"], sample["M"]
    raw = []
    for i in range(args.warmup + args.calls):
        j = i % len(x)
        start = time.perf_counter_ns()
        predictor.predict(x[j], mask[j])
        end = time.perf_counter_ns()
        if i >= args.warmup:
            raw.append(end - start)
    ms = np.asarray(raw) / 1e6
    report = {
        "evidence_kind": predictor.manifest["evidence_kind"],
        "model_hash": predictor.model_hash,
        "sample_hash": sha256_file(args.samples),
        "cpu": platform.processor(),
        "platform": platform.platform(),
        "threads": 1,
        "batch_size": 1,
        "warmup_calls": args.warmup,
        "timed_calls": args.calls,
        "p50_ms": float(np.percentile(ms, 50)),
        "p95_ms": float(np.percentile(ms, 95)),
        "p99_ms": float(np.percentile(ms, 99)),
        "raw_ns": raw,
        "scope": "all available LightGBM heads; excludes feature extraction and geometry/commit",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("p50_ms", "p95_ms", "p99_ms", "timed_calls")}))


if __name__ == "__main__":
    main()
