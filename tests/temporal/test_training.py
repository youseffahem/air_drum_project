import json
import shutil

import numpy as np
import pytest
import torch

from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.data import epoch_indices, load_fold
from spacedrums.models.temporal.export import export_model, latency, load_model
from spacedrums.models.temporal.train import TrainConfig, diagnostics, predictions, train_fold


def test_fold_isolation_and_deterministic_sampling(fold):
    path, _, _ = fold
    c = TemporalConfig("gru", 56, n=4, k=3)
    # A corrupt held-out file must never be opened by training.
    (path / "samples.test.npz").write_bytes(b"DO NOT READ TEST")
    train, val, _ = load_fold(path, c)
    assert not ({m["participant"] for m in train["meta"]} & {m["participant"] for m in val["meta"]})
    np.testing.assert_array_equal(epoch_indices(train, seed=10), epoch_indices(train, seed=10))
    assert not np.array_equal(epoch_indices(train, seed=10), epoch_indices(train, seed=11))
    indices = epoch_indices(train, seed=10, positive_ratio=0.5)
    np.testing.assert_array_equal(indices, epoch_indices(train, seed=10, positive_ratio=0.5))
    assert set(indices) == set(range(train["count"]))
    stats = json.loads((path / "norm_stats.json").read_text())
    stats["train_participants"].extend({m["participant"] for m in val["meta"]})
    (path / "norm_stats.json").write_text(json.dumps(stats))
    with pytest.raises(ValueError, match="provenance"):
        load_fold(path, c)


def test_fold_refuses_overlapping_test_roster_and_aux_mismatch(fold):
    path, _, _ = fold
    c = TemporalConfig("gru", 56, n=4, k=3, auxiliary=True)
    with pytest.raises(ValueError, match="exported H"):
        load_fold(path, c, aux_horizon_s=0.2)
    report = json.loads((path / "report.json").read_text())
    report["parts"]["test"]["participants"] = report["parts"]["train"]["participants"]
    (path / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="leakage"):
        load_fold(path, c, aux_horizon_s=0.1)


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("auxiliary", [False, True])
def test_training_determinism_export_roundtrip_and_latency(fold, tmp_path, family, auxiliary):
    path, _, _ = fold
    c = TemporalConfig(family, 56, n=4, k=3, hidden=8, auxiliary=auxiliary)
    training = TrainConfig(seed=7, epochs=2, lambda_aux=0.1 if auxiliary else 0)
    model, manifest, val = train_fold(
        path, tmp_path / "one", c, training, provenance={"evidence": "SYNTHETIC"}, aux_horizon_s=0.1
    )
    other, repeated, _ = train_fold(
        path, tmp_path / "two", c, training, provenance={"evidence": "SYNTHETIC"}, aux_horizon_s=0.1
    )
    assert manifest["best_validation_score"] == repeated["best_validation_score"]
    for a, b in zip(model.parameters(), other.parameters(), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    parity = export_model(model, tmp_path / "one", val)
    assert parity["passed"] and parity["comparisons"] == 2 * val["count"]
    exported, _ = load_model(tmp_path / "one")
    a, b = predictions(model, val)[0], predictions(exported, val)[0]
    assert diagnostics(a, val) == diagnostics(b, val)
    report = latency(exported, val, family=family, calls=5, warmup=1)
    assert report["results"]["windowed"]["p99_ms"] > 0
    shutil.copy(tmp_path / "one/export.pt", tmp_path / "one/original.pt")
    (tmp_path / "one/export.pt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="content hash"):
        load_model(tmp_path / "one")
