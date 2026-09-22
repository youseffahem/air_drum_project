"""Phase 08 CLI checks: outputs, kind gating, schema-valid real CPU timing logs."""

import json
import sys
from pathlib import Path

import pytest

from spacedrums.contracts import schema as contracts

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def test_feature_config_schema_and_cross_fields():
    from spacedrums.config import ConfigError, load_config

    paths = [ROOT / "configs/prototype.candidate.yaml", ROOT / "configs/features/fs-v1.candidate.yaml"]
    assert load_config(*paths)["features"]["schema_id"] == "fs-v1"
    with pytest.raises(ConfigError, match="1.4"):
        load_config(*paths, overrides={"meta": {"schema_version": "1.3"}})
    with pytest.raises(ConfigError, match="h_max"):
        load_config(
            *paths,
            overrides={
                "features": {"window": {"n": 8, "k": 4, "h": 0.3, "h_max": 0.1, "stride": 1, "g_win": 0}}
            },
        )


def cli_args(tmp_path):
    return [
        "--synthetic-fixture",
        "--out",
        str(tmp_path / "features"),
        "--experiments-dir",
        str(tmp_path / "runs"),
        "--n",
        "8",
        "--k",
        "4",
        "--h",
        ".1",
        "--h-max",
        ".3",
        "--stride",
        "2",
        "--g-win",
        "1",
    ]


@pytest.mark.parametrize("stats_only", [False, True])
def test_feature_and_normalization_cli_generate_selftest_folds(tmp_path, monkeypatch, stats_only):
    import _p08
    import _runlog

    monkeypatch.setattr(_runlog, "hardware_snapshot", lambda **kw: {"cpu_model": "UNIT TEST"})
    assert _p08.main(cli_args(tmp_path), stats_only=stats_only) == 0
    files = list((tmp_path / "features").glob("fold-*/norm_stats.json"))
    assert len(files) == 3
    for path in files:
        doc = json.loads(path.read_text())
        assert doc["source_kind"] == "SYNTHETIC"
        assert doc["dataset_version"].startswith("ds-v0.0-selftest")
    run = json.loads(next((tmp_path / "runs").glob("*/run.json")).read_text())
    contracts.validate("experiment-log", run)
    assert run["status"] == "COMPLETED"
    with pytest.raises(SystemExit):
        _p08.main(cli_args(tmp_path), stats_only=stats_only)


def test_missing_participant_dataset_refused_without_outputs(tmp_path):
    import _p08

    args = cli_args(tmp_path)
    args = args[1:] + ["--manifest", str(tmp_path / "ds-v1.0.json"), "--splits", str(tmp_path / "splits")]
    with pytest.raises(FileNotFoundError):
        _p08.main(args)
    assert not (tmp_path / "features").exists()


def test_latency_cli_measures_real_times_and_validates_log(tmp_path, monkeypatch):
    import _runlog
    import feature_latency

    monkeypatch.setattr(_runlog, "hardware_snapshot", lambda **kw: {"cpu_model": "UNIT TEST"})
    assert (
        feature_latency.main(
            ["--synthetic", "--iterations", "20", "--warmup", "2", "--experiments-dir", str(tmp_path)]
        )
        == 0
    )
    doc = json.loads(next(tmp_path.glob("*/run.json")).read_text())
    contracts.validate("experiment-log", doc)
    for variant in doc["metrics"]["variants"].values():
        assert 0 < variant["p50_ms"] <= variant["p95_ms"] <= variant["max_ms"]
    assert doc["metrics"]["variants"]["full_with_jerk"]["dimension"] == 74
    assert doc["metrics"]["variants"]["largest_group_ablation_without_time"]["dimension"] == 72
