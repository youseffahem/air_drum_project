"""Compare windowed and bounded-stateful GRU on an existing DEV capture only."""

import argparse
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import torch
from _p10 import provenance, write_json

from spacedrums.config import load_config
from spacedrums.features.batch import build_features, load_causal_tracks
from spacedrums.features.normalize import NormStats
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import history_arrays
from spacedrums.models.temporal.adapter import TemporalAnticipator
from spacedrums.models.temporal.data import sha
from spacedrums.models.temporal.export import load_model


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--fold-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("output exists")
    model, m = load_model(args.model_dir)
    torch.set_num_threads(m["training"]["threads"])
    if m["family"] != "gru":
        ap.error("GRU model required")
    path = Path("data/labels/dev-p06-ingest-exp-5/tracks_causal.jsonl")
    schema = FeatureSchema(load_config("data/raw/DEV/dev-p06-ingest-exp-5/config.snapshot.yaml")["zones"])
    stats_path = args.fold_dir / "norm_stats.json"
    if sha(stats_path) != m["norm_stats_id"]:
        ap.error("normalization hash mismatch")
    stats = NormStats.read(
        stats_path,
        fold=m["fold"],
        dataset_version=m["dataset_version"],
        dataset_hash=m["dataset_hash"],
        split_hash=m["split_hash"],
        schema=schema,
    )
    tracks = load_causal_tracks(path, session_id="dev-p06-ingest-exp-5")
    records = build_features(tracks, schema)
    windowed, stateful = TemporalAnticipator(model, m), TemporalAnticipator(model, m, stateful=True)
    histories, features = defaultdict(lambda: deque(maxlen=m["N"])), defaultdict(lambda: deque(maxlen=m["N"]))
    count, max_error = 0, 0.0
    for track, record in zip(tracks, records, strict=True):
        hand = track.hand_id
        if track.reset_reason:
            histories[hand].clear()
            features[hand].clear()
        histories[hand].append(track)
        features[hand].append(record)
        arrays = (
            stats.apply(*history_arrays(list(features[hand]), schema), schema)
            if len(features[hand]) == m["N"]
            else None
        )
        a, b = (
            windowed.predict(list(histories[hand]), arrays),
            stateful.predict(list(histories[hand]), arrays),
        )
        assert (a is None) == (b is None)
        if a is not None:
            np.testing.assert_allclose(a.positions, b.positions, atol=1e-6, rtol=1e-5)
            max_error = max(max_error, float(np.abs(np.asarray(a.positions) - b.positions).max()))
            count += 1
    if not count:
        raise ValueError("no recorded predictions compared")
    write_json(
        args.output,
        {
            **provenance(),
            "source_kind": "DEV_CAPTURE",
            "model_training_kind": m["source_kind"],
            "track_hash": sha(path),
            "export_hash": m["export_hash"],
            "predictions_compared": count,
            "max_abs_error": max_error,
            "atol": 1e-6,
            "rtol": 1e-5,
            "passed": True,
            "limitation": "tip-only feature reassembly, synthetic-trained weights; "
            "parity only, no accuracy claim",
        },
    )


if __name__ == "__main__":
    main()
