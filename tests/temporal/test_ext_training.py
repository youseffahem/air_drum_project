"""Phase 12 training on the SYNTHETIC Phase 08 fold: no extension == Phase 10, determinism, export
parity per extension, fold isolation, and the E5 base equal to Baseline B's CV extrapolation."""

import json
import shutil

import numpy as np
import pytest
import torch

from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.data import load_fold
from spacedrums.models.temporal.export import export_model, latency
from spacedrums.models.temporal.ext import ExtensionConfig, load_extension_model
from spacedrums.models.temporal.ext.long_horizon import select_grid
from spacedrums.models.temporal.ext.train import train_extension_fold, training_targets
from spacedrums.models.temporal.train import TrainConfig, predictions, train_fold
from spacedrums.prediction.rule_based import extrapolate

PROVENANCE = {"evidence": "SYNTHETIC"}
CONFIGS = {
    "velocity": {"representation": "velocity"},
    "polynomial": {"representation": "polynomial"},
    "mixture": {"representation": "mixture", "modes": 2},
    "gaussian": {"uncertainty": "gaussian"},
    "residual": {"residual": "cv", "residual_features": (10, 11)},
    "two-rate": {"k": 3, "steps": (1, 2, 4)},
    "tt": {"family": "tt", "layers": 1, "attention_heads": 2, "feedforward": 8},
}


def config(family="gru", **kwargs):
    return ExtensionConfig(**{"family": family, "features": 56, "n": 4, "k": 3, "hidden": 8, **kwargs})


@pytest.mark.parametrize("family", ["gru", "tcn"])
def test_no_extension_reproduces_phase10_training_bit_for_bit(fold, tmp_path, family):
    path, _, _ = fold
    training = TrainConfig(seed=7, epochs=2)
    phase10, m10, _ = train_fold(
        path,
        tmp_path / "p10",
        TemporalConfig(family, 56, n=4, k=3, hidden=8),
        training,
        provenance=PROVENANCE,
    )
    ext, m12, _, _ = train_extension_fold(
        path, tmp_path / "p12", config(family), training, provenance=PROVENANCE, variant="ref"
    )
    assert m12["extensions"] == [] and m10["best_validation_score"] == m12["best_validation_score"]
    a, b = phase10.state_dict(), ext.state_dict()
    assert list(a) == list(b)
    for key in a:
        torch.testing.assert_close(a[key], b[key], atol=0, rtol=0)


@pytest.mark.parametrize("variant", sorted(CONFIGS))
def test_extension_training_is_deterministic_and_exports_with_parity(fold, tmp_path, variant):
    path, _, _ = fold
    c = config(**CONFIGS[variant])
    training = TrainConfig(seed=3, epochs=2)
    (path / "samples.test.npz").write_bytes(b"DO NOT READ TEST")  # never opened by training
    model, manifest, _, val = train_extension_fold(
        path, tmp_path / "one", c, training, provenance=PROVENANCE, variant=variant
    )
    other, repeated, _, _ = train_extension_fold(
        path, tmp_path / "two", c, training, provenance=PROVENANCE, variant=variant
    )
    assert manifest["checkpoint_hash"] == repeated["checkpoint_hash"]
    for a, b in zip(model.parameters(), other.parameters(), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    assert manifest["extensions"] == list(c.extensions) and manifest["offsets_s"] == pytest.approx(
        c.offsets_s
    )
    history = json.loads((tmp_path / "one/training.json").read_text())
    assert history[-1]["validation"]["error_by_offset"][-1]["offset_s"] == pytest.approx(c.offsets_s[-1])
    if variant == "mixture":
        assert (
            history[-1]["validation"]["mixture"]["best_of_m_ade"]
            <= history[-1]["validation"]["mixture"]["most_probable_ade"]
        )
    parity = export_model(model, tmp_path / "one", val)
    assert parity["passed"] and parity["comparisons"] == 2 * val["count"]
    exported, loaded_manifest = load_extension_model(tmp_path / "one")
    for a, b in zip(predictions(model, val), predictions(exported, val), strict=True):
        torch.testing.assert_close(a, b, atol=1e-6, rtol=1e-5)
    assert latency(exported, val, family="windowed", calls=3, warmup=1)["results"]["windowed"]["p99_ms"] > 0
    eager, _ = load_extension_model(tmp_path / "one", exported=False)
    for a, b in zip(predictions(model, val), predictions(eager, val), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    shutil.copy(tmp_path / "one/export.pt", tmp_path / "one/original.pt")
    (tmp_path / "one/export.pt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="content hash"):
        load_extension_model(tmp_path / "one")
    assert loaded_manifest["variant"] == variant


def test_two_rate_targets_are_the_dense_grid_columns(fold):
    path, _, _ = fold
    two = config(k=3, steps=(1, 2, 4))
    dense = config(k=4)
    train_two, _, _ = load_fold(path, two.data_view)
    train_dense, _, _ = load_fold(path, dense.data_view)
    select_grid(train_two, two)
    select_grid(train_dense, dense)
    for key in ("target", "target_mask"):
        torch.testing.assert_close(train_two["tensors"][key], train_dense["tensors"][key][:, [0, 1, 3]])
    targets, mask, offsets = training_targets(train_two)
    assert targets.shape[1] == 3 and offsets == pytest.approx((1 / 30, 2 / 30, 4 / 30))
    with pytest.raises(ValueError, match="dense grid"):
        select_grid(train_two, dense)


def test_residual_base_is_baseline_b_constant_velocity_on_the_raw_features(fold, tmp_path):
    path, _, _ = fold
    c = config("tcn", residual="cv", residual_features=(10, 11))
    model, manifest, train, _ = train_extension_fold(
        path, tmp_path / "r", c, TrainConfig(seed=1, epochs=1), provenance=PROVENANCE, variant="e5"
    )
    stats = json.loads((path / "norm_stats.json").read_text())
    assert manifest["residual_statistics"] == {
        "center": [stats["center"][10], stats["center"][11]],
        "scale": [stats["scale"][10], stats["scale"][11]],
    }
    t = train["tensors"]
    rows = torch.nonzero(t["mask"][:, -1, 10] & t["mask"][:, -1, 11]).flatten()[:20]
    assert len(rows)
    base = model.base(t["x"][rows], t["mask"][rows]).numpy()
    for row, predicted in zip(rows.tolist(), base, strict=True):
        v = [float(t["x"][row, -1, i]) * stats["scale"][i] + stats["center"][i] for i in (10, 11)]
        expected = [extrapolate((0.0, 0.0), v, None, j + 1, c.dt_step)[0] for j in range(c.k)]
        np.testing.assert_allclose(predicted, expected, rtol=1e-5, atol=1e-6)


def test_extension_training_refuses_undeclared_settings(fold, tmp_path):
    path, _, _ = fold
    with pytest.raises(ValueError, match="auxiliary logit"):
        train_extension_fold(
            path, tmp_path / "a", config(), TrainConfig(lambda_aux=0.1), provenance=PROVENANCE, variant="x"
        )
    with pytest.raises(ValueError, match="uniform output grid"):
        train_extension_fold(
            path,
            tmp_path / "b",
            config(k=3, steps=(1, 2, 4)),
            TrainConfig(velocity_weight=0.1),
            provenance=PROVENANCE,
            variant="x",
        )
