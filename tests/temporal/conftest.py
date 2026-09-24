"""SYNTHETIC model fixtures, never participant evidence."""

import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from _p08_fixture import synthetic_fixture  # noqa: E402

from spacedrums.config import load_config  # noqa: E402
from spacedrums.data.feature_dataset import export_folds  # noqa: E402
from spacedrums.features.windows import WindowParams  # noqa: E402


@pytest.fixture(autouse=True)
def one_thread():
    torch.set_num_threads(1)


@pytest.fixture
def fold(tmp_path):
    cfg = load_config(ROOT / "configs/prototype.candidate.yaml")
    manifest, cv, sessions = synthetic_fixture(cfg)
    export_folds(manifest, cv, sessions, tmp_path / "folds", WindowParams(4, 6, 0.1, 0.3, 2, 0))
    return tmp_path / "folds/fold-0", sessions, cfg
