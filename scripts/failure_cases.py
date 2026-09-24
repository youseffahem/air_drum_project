"""Plot worst validation trajectory errors and index available replay failure events."""

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from _p10 import write_json  # noqa: E402

from spacedrums.models.temporal import TemporalConfig  # noqa: E402
from spacedrums.models.temporal.data import read_samples, sha  # noqa: E402
from spacedrums.models.temporal.export import load_model  # noqa: E402
from spacedrums.models.temporal.train import predictions  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--samples", type=Path, required=True)
    ap.add_argument("--replay-dir", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    model, m = load_model(args.model_dir)
    if sha(args.samples) != m["val_samples_hash"] or args.output.exists():
        ap.error("validation hash mismatch or output already exists")
    sample = read_samples(args.samples, TemporalConfig(**m["config"]), aux_horizon_s=m["aux_horizon_s"])
    predicted = predictions(model, sample)[0].numpy()
    target, mask = sample["tensors"]["target"].numpy(), sample["tensors"]["target_mask"].numpy()
    error = np.linalg.norm(predicted - target, axis=-1)
    means = np.where(mask, error, 0).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
    rows = np.argsort(-means, kind="stable")[:6]
    fig, axes = plt.subplots(2, 3, figsize=(11, 7), layout="constrained")
    catalogue = []
    for ax, index in zip(axes.flat, rows, strict=False):
        actual = np.vstack((np.zeros(2), target[index][mask[index]]))
        estimate = np.vstack((np.zeros(2), predicted[index]))
        ax.plot(actual[:, 0], actual[:, 1], "o-", label="Future causal tracker")
        ax.plot(estimate[:, 0], estimate[:, 1], "x--", label="Predicted")
        ax.invert_yaxis()
        ax.set_title(
            f"{sample['meta'][index]['participant']} {sample['meta'][index]['hand_id']} "
            f"frame {sample['meta'][index]['frame_id']}\n"
            f"ADE {means[index]:.4f}"
        )
        ax.set(xlabel="Tip displacement x (ROI)", ylabel="Tip displacement y (ROI)")
        ax.legend(fontsize=7)
        catalogue.append(
            {
                "metadata": sample["meta"][index],
                "ade": float(means[index]),
                "prediction": predicted[index].tolist(),
                "actual": actual.tolist(),
            }
        )
    fig.suptitle(m["source_kind"] + " validation: worst trajectory cases; no physical-tip claim")
    args.output.mkdir(parents=True)
    fig.savefig(args.output / "worst-trajectories.png", dpi=150)
    plt.close(fig)
    events = []
    if args.replay_dir:
        for path in sorted(args.replay_dir.rglob("events.jsonl")):
            events.extend({**json.loads(line), "source": str(path)} for line in path.read_text().splitlines())
    matched = [e for e in events if e["kind"] == "MATCH" and e.get("t_impact_pred") is not None]
    late = sorted(matched, key=lambda e: e["t_impact_pred"] - e["t_impact_est"], reverse=True)[:10]
    early = sorted(matched, key=lambda e: e["t_impact_pred"] - e["t_impact_est"])[:10]
    write_json(
        args.output / "catalogue.json",
        {
            "source_kind": m["source_kind"],
            "export_hash": m["export_hash"],
            "trajectories": catalogue,
            "largest_positive_TE_pred": late,
            "smallest_TE_pred": early,
            "false_positives": [e for e in events if e["kind"] == "FP"][:30],
            "false_negatives": [e for e in events if e["kind"] == "FN"][:30],
            "wrong_zone": [e for e in matched if e["zone_pred"] != e["zone_gt"]][:30],
            "timing_sign": "TE_pred = predicted impact minus GT impact; "
            "positive means later predicted impact, not early sound",
            "pending": [
                "participant fake swings/stops",
                "fast-hit FN attribution",
                "adjacent-zone participant errors",
                "ROI boundary",
                "unusual grip",
                "physical sound timing",
            ],
        },
    )


if __name__ == "__main__":
    main()
