"""TEST-CAUSAL-1/2 and independent streaming/serialization invariants."""

import numpy as np
import pytest
import torch

from spacedrums.models.temporal import TemporalConfig, build_model
from spacedrums.models.temporal.gru import BoundedGRUState
from spacedrums.models.temporal.losses import auxiliary_loss, trajectory_loss


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("auxiliary", [False, True])
def test_causal_future_perturbation_and_history_truncation(family, auxiliary):
    torch.manual_seed(2)
    c = TemporalConfig(family, 5, n=4, k=3, auxiliary=auxiliary)
    model = build_model(c).eval()
    x = torch.randn(2, 13, 5)
    mask = torch.rand_like(x) > 0.2
    changed = x.clone()
    changed[:, 8:] += 1000
    for a, b in zip(model(x[:, :8], mask[:, :8]), model(changed[:, :8], mask[:, :8]), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    for a, b in zip(model(x[:, :8], mask[:, :8]), model(x[:, 4:8], mask[:, 4:8]), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    poisoned = x.clone()
    poisoned[~mask] = float("nan")
    for a, b in zip(model(x, mask), model(poisoned, mask), strict=True):
        torch.testing.assert_close(a, b, atol=0, rtol=0)
    assert not torch.equal(model(x[:, :8], mask[:, :8])[0], model(x[:, 5:8], mask[:, 5:8])[0])
    if family == "tcn":
        a, b = model.encode(x, mask), model.encode(changed, mask)
        torch.testing.assert_close(a[:, :, :8], b[:, :, :8], atol=0, rtol=0)
    else:
        state = torch.zeros(c.layers, 2, c.hidden)
        for i in range(8):
            state = model.step(x[:, i], mask[:, i], state)
        other = torch.zeros_like(state)
        for i in range(8):
            other = model.step(changed[:, i], mask[:, i], other)
        torch.testing.assert_close(state, other, atol=0, rtol=0)


def test_receptive_field_and_left_padding():
    with pytest.raises(ValueError, match="receptive"):
        TemporalConfig("tcn", 2, n=16, kernel=2, dilations=(1, 2))
    c = TemporalConfig("tcn", 2, n=13, kernel=3, dilations=(1, 2))
    assert c.receptive_field == 13
    model = build_model(c)
    assert all(layer.conv.padding == (0,) for block in model.blocks for layer in (block.first, block.second))


@pytest.mark.parametrize("layers", [1, 2])
def test_bounded_gru_state_matches_windows_with_gaps_and_changed_window_features(layers):
    torch.manual_seed(10)
    model = build_model(TemporalConfig("gru", 3, n=5, layers=layers)).eval()
    state = BoundedGRUState(model)
    x, mask = torch.randn(16, 3), torch.ones(16, 3, dtype=torch.bool)
    mask[8] = False
    for i in range(4, len(x)):
        window, m = x[i - 4 : i + 1].clone(), mask[i - 4 : i + 1]
        if i >= 12:
            window[:, -1] = torch.arange(5)  # Phase 08 window-relative elapsed feature.
        expected, actual = model(window[None], m[None]), state(window, m)
        for a, b in zip(expected, actual, strict=True):
            torch.testing.assert_close(a, b, atol=1e-6, rtol=1e-5)
        assert state.state.shape[1] == 5
    assert state.rebuilds > 1 and state.incremental_steps > 0
    state.reset()
    assert state.state is None


@pytest.mark.parametrize("kind", ["l1", "mse", "huber"])
def test_losses_ignore_masked_nan_and_have_zero_masked_gradient(kind):
    pred = torch.tensor([[[1.0, 2.0], [8.0, 9.0]]], requires_grad=True)
    target = torch.tensor([[[0.0, 0.0], [float("nan"), float("inf")]]])
    mask = torch.tensor([[True, False]])
    loss = trajectory_loss(
        pred, target, mask, kind=kind, weights=torch.tensor([2.0, 7.0]), velocity_weight=0.1
    )
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(pred.grad).all()
    assert torch.equal(pred.grad[0, 1], torch.zeros(2))
    empty = trajectory_loss(pred, target, torch.zeros_like(mask), kind=kind)
    assert float(empty.detach()) == 0
    assert (
        float(auxiliary_loss(torch.ones(2), torch.full((2,), float("nan")), torch.zeros(2, dtype=torch.bool)))
        == 0
    )


def test_loss_weighting_and_velocity():
    pred = torch.tensor([[[1.0, 1.0], [3.0, 3.0]]])
    target, mask = torch.zeros_like(pred), torch.ones(1, 2, dtype=torch.bool)
    assert trajectory_loss(pred, target, mask, kind="l1", weights=torch.tensor([3.0, 1.0])).item() == 1.5
    assert trajectory_loss(pred, target, mask, kind="mse", velocity_weight=1, dt_step=2).item() == 6
    with pytest.raises(ValueError):
        trajectory_loss(pred, target, mask, weights=torch.tensor([-1.0, 2.0]))
    assert trajectory_loss(
        pred, target, mask, kind="l1", weights=torch.tensor([0.03, 0.01])
    ).item() == pytest.approx(1.5)


def test_fixed_grid_never_bridges_gaps_or_extrapolates():
    from spacedrums.models.temporal.data import fixed_grid

    target = np.array([[[0.04, 0.08], [0.10, 0.20], [999.0, 999.0]]])
    times = np.array([[0.04, 0.1, 0.15]])
    out, mask = fixed_grid(target, times, np.array([[True, True, False]]), 4, 0.03)
    np.testing.assert_allclose(out[0, :3], [[0.03, 0.06], [0.06, 0.12], [0.09, 0.18]])
    assert mask.tolist() == [[True, True, True, False]]
    _, mask = fixed_grid(target, times, np.array([[True, False, True]]), 4, 0.03)
    assert mask.tolist() == [[True, False, False, False]]
