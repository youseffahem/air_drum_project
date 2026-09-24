"""Measure exported batch-one CPU inference on a hashed fold validation archive."""

import argparse
from pathlib import Path

from _p10 import hardware, provenance, write_json

from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.data import read_samples, sha
from spacedrums.models.temporal.export import latency, load_model


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--samples", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--calls", type=int, default=500)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()
    model, manifest = load_model(args.model_dir)
    if sha(args.samples) != manifest["val_samples_hash"] or args.output.exists():
        ap.error("validation sample hash mismatch or output already exists")
    sample = read_samples(
        args.samples, TemporalConfig(**manifest["config"]), aux_horizon_s=manifest["aux_horizon_s"]
    )
    report = latency(model, sample, family=manifest["family"], calls=args.calls, threads=args.threads)
    report.update(
        **provenance(),
        hardware=hardware(),
        export_hash=manifest["export_hash"],
        evidence="DEVELOPMENT CPU COMPUTE on " + manifest["source_kind"],
    )
    write_json(args.output, report)


if __name__ == "__main__":
    main()
