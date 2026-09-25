"""TEST-CAUSAL-1/2 on the Phase 11 multi-task model: every head output, both encoders."""

import pytest
import torch
from mt_helpers import mt_config

from spacedrums.models.temporal.config import TASKS, build_mt_model
from spacedrums.models.temporal.gru import BoundedGRUState


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("heads", [TASKS, TASKS[1:]])
def test_future_perturbation_truncation_and_masked_payload_invariance(family, heads):
    torch.manual_seed(3)
    model = build_mt_model(mt_config(family, heads, features=5, n=4, k=3, dt=1 / 30)).eval()
    x = torch.randn(2, 13, 5)
    mask = torch.rand_like(x) > 0.2
    future = x.clone()
    future[:, 8:] += 1000  # TEST-CAUSAL-1: frames after t_now change nothing at t_now
    same = (model(x[:, :8], mask[:, :8]), model(future[:, :8], mask[:, :8]))
    truncated = model(x[:, 4:8], mask[:, 4:8])  # TEST-CAUSAL-2: only the declared N frames matter
    poisoned = x.clone()
    poisoned[~mask] = float("nan")
    for a, b, c, d, e in zip(*same, truncated, model(x, mask), model(poisoned, mask), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
        torch.testing.assert_close(a, c, atol=0, rtol=0)
        torch.testing.assert_close(d, e, atol=0, rtol=0)
    changed = model(x[:, 5:8], mask[:, 5:8])  # a shorter history is a different input (negative control)
    assert any(not torch.equal(a, b) for a, b in zip(same[0], changed, strict=True) if a.abs().sum())


def test_bounded_gru_state_parity_for_all_heads():
    torch.manual_seed(4)
    model = build_mt_model(mt_config("gru", TASKS, features=3, n=5, k=3, dt=1 / 30)).eval()
    cache = BoundedGRUState(model)
    x, mask = torch.randn(14, 3), torch.ones(14, 3, dtype=torch.bool)
    mask[7] = False
    for i in range(4, len(x)):
        window, m = x[i - 4 : i + 1], mask[i - 4 : i + 1]
        for a, b in zip(model(window[None], m[None]), cache(window, m), strict=True):
            torch.testing.assert_close(a, b, atol=1e-6, rtol=1e-5)
    assert cache.incremental_steps > 0
