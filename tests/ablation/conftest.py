"""Bound CPU threads for deterministic SYNTHETIC/DEV tests."""

import pytest
import torch


@pytest.fixture(autouse=True)
def one_thread():
    torch.set_num_threads(1)
