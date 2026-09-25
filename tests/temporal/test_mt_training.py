"""Phase 11 training: Phase 10 equivalence, determinism, export, isolation, label contracts."""

import json

import numpy as np
import pytest
import torch
from mt_helpers import ZONES

from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.config import TASKS, MultiTaskConfig
from spacedrums.models.temporal.export import export_model, load_model, load_mt_model
from spacedrums.models.temporal.mt_train import (
    MultiTaskLossConfig,
    load_mt_fold,
    mt_predictions,
    task_metrics,
    train_mt_fold,
)
from spacedrums.models.temporal.train import TrainConfig, train_fold


def _config(family="gru", heads=TASKS, **kwargs):
    base = TemporalConfig(family, 56, n=4, k=3, hidden=8)
    kwargs.setdefault("h_max_s", 0.3)
    return MultiTaskConfig(base, heads=heads, zone_ids=ZONES if "zone" in heads else (), **kwargs)


@pytest.mark.parametrize("family", ["gru", "tcn"])
def test_trajectory_only_multitask_is_the_phase10_model_exactly(fold, tmp_path, family):
    path, _, _ = fold
    training = TrainConfig(seed=7, epochs=2)
    single, m10, _ = train_fold(
        path, tmp_path / "p10", TemporalConfig(family, 56, n=4, k=3, hidden=8), training, provenance={}
    )
    multi, m11, _ = train_mt_fold(
        path,
        tmp_path / "p11",
        _config(family, ("trajectory",)),
        training,
        MultiTaskLossConfig(),
        provenance={},
    )
    assert (
        m10["best_epoch"] == m11["best_epoch"]
        and m10["best_validation_score"] == m11["best_validation_score"]
    )
    for (name, a), (other, b) in zip(single.state_dict().items(), multi.state_dict().items(), strict=True):
        assert name == other
        torch.testing.assert_close(a, b, atol=0, rtol=0)


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("weighting", ["fixed", "trajectory_dominant", "uncertainty", "gradnorm"])
def test_multitask_determinism_export_parity_and_tamper(fold, tmp_path, family, weighting):
    path, _, _ = fold
    config, training = _config(family), TrainConfig(seed=3, epochs=2)
    loss = MultiTaskLossConfig(weighting=weighting)
    runs = [
        train_mt_fold(
            path,
            tmp_path / name,
            config,
            training,
            loss,
            provenance={"evidence": "SYNTHETIC"},
            aux_horizon_s=0.1,
        )
        for name in ("one", "two")
    ]
    (model, manifest, val), (other, repeated, _) = runs
    assert manifest["best_task_weights"] == repeated["best_task_weights"]
    for a, b in zip(model.parameters(), other.parameters(), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    assert manifest["live_eligible"] and manifest["heads"] == list(TASKS)
    assert manifest["task_counts"]["train"]["impact_labelled"] > 0
    parity = export_model(model, tmp_path / "one", val)
    assert parity["passed"] and parity["comparisons"] == 2 * val["count"]
    exported, loaded = load_mt_model(tmp_path / "one")
    scaling = loaded["target_scaling"]
    eager, reloaded = mt_predictions(model, val), mt_predictions(exported, val)
    for a, b in zip(eager, reloaded, strict=True):
        torch.testing.assert_close(a, b, atol=1e-6, rtol=1e-5)
    metrics = task_metrics(config, scaling, reloaded, val)
    assert set(metrics) == set(TASKS) and metrics["zone"]["n"] == metrics["tti"]["n"] > 0
    with pytest.raises(ValueError, match="hash"):
        load_model(tmp_path / "one")  # the Phase 10 loader refuses a multi-task package
    (tmp_path / "one/export.pt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="content hash"):
        load_mt_model(tmp_path / "one")


def test_conflict_sampling_is_read_only(fold, tmp_path):
    path, _, _ = fold
    config, training = _config(), TrainConfig(seed=5, epochs=1)
    plain, _, _ = train_mt_fold(
        path, tmp_path / "a", config, training, MultiTaskLossConfig(), provenance={}, aux_horizon_s=0.1
    )
    sampled, manifest, _ = train_mt_fold(
        path,
        tmp_path / "b",
        config,
        training,
        MultiTaskLossConfig(conflict_every=2),
        provenance={},
        aux_horizon_s=0.1,
    )
    for a, b in zip(plain.parameters(), sampled.parameters(), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    rows = json.loads((tmp_path / "b/conflicts.json").read_text())
    assert manifest["conflict_samples"] == len(rows) > 0
    cosines = [v["cosine"] for r in rows for v in r["tasks"].values() if v["cosine"] is not None]
    assert cosines and all(-1 - 1e-6 <= c <= 1 + 1e-6 for c in cosines)


def test_label_contracts_and_heldout_isolation(fold, tmp_path):
    path, _, _ = fold
    (path / "samples.test.npz").write_bytes(b"DO NOT READ TEST")  # never opened by training
    with pytest.raises(ValueError, match="zone"):
        load_mt_fold(
            path,
            MultiTaskConfig(
                TemporalConfig("gru", 56, n=4, k=3), heads=("trajectory", "zone"), zone_ids=("hihat",)
            ),
            aux_horizon_s=0.1,
        )
    with pytest.raises(ValueError, match="H_max"):
        load_mt_fold(path, _config(heads=("trajectory", "tti"), h_max_s=0.15), aux_horizon_s=0.1)
    for horizon in (None, 0.2):
        with pytest.raises(ValueError, match="exported H"):
            load_mt_fold(path, _config(heads=("trajectory", "strike")), aux_horizon_s=horizon)
    with pytest.raises(ValueError, match="lambda_aux"):
        train_mt_fold(
            path, tmp_path / "x", _config(), TrainConfig(lambda_aux=0.1), MultiTaskLossConfig(), provenance={}
        )
    train, val, _ = load_mt_fold(path, _config(), aux_horizon_s=0.1)
    impact = train["mt"]["impact_mask"]
    assert impact.any() and not train["mt"]["tti"][impact].le(0).any()
    # Anchor = current tip: absolute impact minus the displacement target gives the labelled point.
    labelled = train["mt"]["position"][impact].numpy() + train["anchor"][impact.numpy()]
    np.testing.assert_allclose(labelled, [[0.4, 0.58]] * int(impact.sum()), atol=1e-6)


def test_intensity_scaling_is_fitted_on_train_rows_only(fold, tmp_path):
    path, _, _ = fold
    before = train_mt_fold(
        path,
        tmp_path / "a",
        _config(),
        TrainConfig(epochs=1),
        MultiTaskLossConfig(),
        provenance={},
        aux_horizon_s=0.1,
    )[1]
    with np.load(path / "samples.val.npz", allow_pickle=False) as archive:
        arrays = {k: archive[k].copy() for k in archive.files}
    aux = [json.loads(str(a)) for a in arrays["aux"]]
    for a in aux:
        a["intensity"] = a["intensity"] * 50 + 7
    arrays["aux"] = np.asarray([json.dumps(a, sort_keys=True) for a in aux], dtype=str)
    np.savez_compressed(path / "samples.val.npz", **arrays)
    after = train_mt_fold(
        path,
        tmp_path / "b",
        _config(),
        TrainConfig(epochs=1),
        MultiTaskLossConfig(),
        provenance={},
        aux_horizon_s=0.1,
    )[1]
    assert before["target_scaling"] == after["target_scaling"]
    assert before["target_scaling"]["intensity"]["fit"] == "train fold impact rows only"
