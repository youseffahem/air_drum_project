"""Window-level GBDT diagnostics; not a substitute for event replay metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from spacedrums.data.labels.schema import sha256_file
from spacedrums.eval.metrics import trajectory_metrics
from spacedrums.models.gbdt.predict import GBDTPredictor
from spacedrums.models.gbdt.train import load_samples


def _interpolate(points: dict, k: int) -> np.ndarray:
    anchors = [(0, (0.0, 0.0))] + sorted((i + 1, p) for i, p in points.items())
    if not anchors or anchors[-1][0] != k:
        raise ValueError("last displacement head missing")
    return np.stack(
        [
            np.interp(np.arange(1, k + 1), [i for i, _ in anchors], [p[axis] for _, p in anchors])
            for axis in range(2)
        ],
        axis=-1,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    predictor = GBDTPredictor(args.model_dir)
    sample = load_samples(args.samples)
    if str(sample["feature_schema_hash"]) != predictor.manifest["feature_schema_hash"]:
        raise ValueError("model/sample feature schema mismatch")
    participants = {m["participant"] for m in sample["meta_decoded"]}
    if participants & set(predictor.manifest["train_participants"]):
        raise ValueError("diagnostic partition overlaps training participants")
    outputs = [predictor.predict(x, m) for x, m in zip(sample["X"], sample["M"], strict=True)]
    aux = sample["aux_decoded"]
    known = np.asarray([bool(a["strike_mask"]) for a in aux])
    truth = np.asarray([bool(a["strike_within_H"]) for a in aux])
    probability = np.asarray([o["strike_probability"] for o in outputs])
    positive = np.asarray([bool(a["tti_mask"]) for a in aux])
    tti_error = [
        abs(o["tti"] - a["tti"])
        for o, a, ok in zip(outputs, aux, positive, strict=True)
        if ok and o["tti"] is not None
    ]
    zone_truth = [
        (o["zone_id"], a["zone_id"])
        for o, a, ok in zip(outputs, aux, positive, strict=True)
        if ok and o["zone_id"] is not None and a["zone_id"] is not None
    ]
    k = sample["T"].shape[1]
    pred_t = np.stack([_interpolate(o["displacements"], k) for o in outputs])
    report = {
        "evidence_kind": predictor.manifest["evidence_kind"],
        "scope": "window-level diagnostics; no geometry or commit; no event FP/min or lead-time claim",
        "model_hash": predictor.model_hash,
        "samples_hash": sha256_file(args.samples),
        "participants": sorted(participants),
        "n_windows": len(outputs),
        "strike_known": int(known.sum()),
        "strike_positives": int((truth & known).sum()),
        "strike_logloss": float(
            -np.mean(
                truth[known] * np.log(np.clip(probability[known], 1e-9, 1))
                + (~truth[known]) * np.log(np.clip(1 - probability[known], 1e-9, 1))
            )
        )
        if known.any()
        else None,
        "tti_mae_s": float(np.mean(tti_error)) if tti_error else None,
        "tti_n": len(tti_error),
        "zone_accuracy": sum(p == g for p, g in zone_truth) / len(zone_truth) if zone_truth else None,
        "zone_n": len(zone_truth),
        "trajectory": trajectory_metrics(pred_t, sample["T"], sample["T_mask"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("evidence_kind", "n_windows", "strike_logloss", "tti_mae_s")}))


if __name__ == "__main__":
    main()
