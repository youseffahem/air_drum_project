"""Small analytic TorchScript fixture. SYNTHETIC engineering evidence only; unique module name."""

import json
import sys
from pathlib import Path

import pytest
import torch

from spacedrums.config import load_config
from spacedrums.features.schema import FeatureSchema
from spacedrums.models.temporal.config import TemporalConfig, build_model
from spacedrums.prediction.model_loader import file_hash

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _p13 import compare_records, parity, pipeline  # noqa: E402, F401


@pytest.fixture
def model_cfg(tmp_path):
    torch.set_num_threads(1)
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml").data
    schema = FeatureSchema(cfg["zones"])
    c = TemporalConfig("gru", schema.dimension, n=2, k=4, dt_step=1 / 30, hidden=8, auxiliary=True)
    model = build_model(c).eval()
    with torch.no_grad():
        model.head.trajectory.weight.zero_()
        model.head.trajectory.bias.copy_(torch.tensor([0.0, 0.04, 0.0, 0.08, 0.0, 0.12, 0.0, 0.16]))
        model.head.aux.weight.zero_()
        model.head.aux.bias.fill_(10)
    torch.jit.script(model).save(str(tmp_path / "export.pt"))
    stats = {
        "fold": 0,
        "dataset_version": "ds-v0.0-selftest-p13",
        "dataset_hash": "fixture",
        "split_hash": "fixture",
        "feature_schema_id": "fs-v1",
        "feature_schema_hash": schema.fingerprint,
        "center": [0.0] * schema.dimension,
        "scale": [1.0] * schema.dimension,
        "usable": [True] * schema.dimension,
    }
    (tmp_path / "norm_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    manifest = {
        **{
            k: stats[k]
            for k in (
                "fold",
                "dataset_version",
                "dataset_hash",
                "split_hash",
                "feature_schema_id",
                "feature_schema_hash",
            )
        },
        "family": "gru",
        "config": c.to_dict(),
        "config_hash": c.config_hash,
        "N": c.n,
        "K": c.k,
        "F": c.features,
        "dt_step": c.dt_step,
        "export_hash": file_hash(tmp_path / "export.pt"),
        "checkpoint_hash": "sha256:" + "0" * 64,
        "norm_stats_id": file_hash(tmp_path / "norm_stats.json"),
        "model_id": "synthetic-analytic-p13",
        "source_kind": "SYNTHETIC",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    cfg["meta"]["schema_version"] = "1.6"
    cfg["features"] = {
        "schema_id": "fs-v1",
        "groups": list(schema.groups),
        "epsilon": 1e-6,
        "tts_clip_s": 2.0,
    }
    cfg["anticipator"].update(
        type="model",
        K=c.k,
        dt_step_s=c.dt_step,
        model={
            "path": str(tmp_path),
            "hash": manifest["export_hash"],
            "runtime": "torchscript",
            "manifest_hash": file_hash(tmp_path / "manifest.json"),
            "N": 2,
            "family": "gru",
            "norm_stats_path": str(tmp_path / "norm_stats.json"),
            "intra_op_threads": 1,
            "feature_schema_id": "fs-v1",
            "cadence_window_frames": 15,
            "cadence_tolerance": 0.25,
        },
        fallback={
            "enabled": False,
            "to": "B",
            "budget_s": 0.01,
            "processing_budget_s": 0.1,
            "window_frames": 5,
            "cooldown_s": 0,
            "automatic_recovery": False,
        },
    )
    cfg["arms"] = {"active": "C-GRU", "shadow": ["A", "B"]}
    return cfg
