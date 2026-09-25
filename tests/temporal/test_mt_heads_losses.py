"""Phase 11 Task 11.1/11.2: head shapes, masked losses (no imputation), weighting schemes."""

import pytest
import torch
from mt_helpers import ZONES, mt_config

from spacedrums.models.temporal.config import TASKS, MultiTaskConfig, TemporalConfig, build_mt_model
from spacedrums.models.temporal.losses import (
    TaskWeighting,
    auxiliary_loss,
    decode_tti,
    masked_regression,
    trajectory_loss,
    tti_loss,
    zone_loss,
)


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("heads", [TASKS, ("trajectory",), ("trajectory", "zone"), TASKS[1:]])
@pytest.mark.parametrize("tti_mode", ["direct", "bins"])
def test_head_shapes_disabled_heads_are_zero_and_torchscript_matches(family, heads, tti_mode):
    torch.manual_seed(0)
    config = mt_config(family, heads, n=4, k=3, tti_mode=tti_mode)
    model = build_mt_model(config).eval()
    x, mask = torch.randn(5, 4, 56), torch.rand(5, 4, 56) > 0.3
    out = model(x, mask)
    widths = {"direct": 1, "bins": config.tti_bins}
    shapes = [(5, 3, 2), (5,), (5, widths[tti_mode]), (5, len(ZONES) if "zone" in heads else 1), (5, 2), (5,)]
    assert [tuple(o.shape) for o in out] == shapes
    for task, value in zip(TASKS, out, strict=True):
        assert (task in heads) or not value.abs().sum()
    scripted = torch.jit.script(model)
    for a, b in zip(out, scripted(x, mask), strict=True):
        torch.testing.assert_close(a, b, atol=1e-6, rtol=1e-5)


def test_multitask_config_validation_and_canonical_hash():
    base = TemporalConfig("gru", 56, n=4, k=3)
    a = MultiTaskConfig(base, heads=("zone", "trajectory"), zone_ids=ZONES)
    b = MultiTaskConfig(base, heads=("trajectory", "zone"), zone_ids=ZONES)
    assert a.heads == ("trajectory", "zone") and a.config_hash == b.config_hash
    assert MultiTaskConfig.from_dict(a.to_dict()) == a and a.live_eligible
    assert not MultiTaskConfig(base, heads=("strike", "tti"), h_max_s=0.3).live_eligible
    for bad in (
        dict(heads=("zone",)),  # zone head without zone ids
        dict(heads=("trajectory",), zone_ids=ZONES),  # zone ids without the head
        dict(heads=("trajectory", "trajectory")),
        dict(heads=("trajectory", "force")),
        dict(heads=("tti",), h_max_s=0.05),  # H_max below K * dt_step
        dict(heads=("tti",), tti_mode="quantile"),
    ):
        with pytest.raises(ValueError):
            MultiTaskConfig(base, **bad)
    with pytest.raises(ValueError, match="auxiliary logit"):
        MultiTaskConfig(TemporalConfig("gru", 56, auxiliary=True), heads=("trajectory",))


def test_sample_without_impact_contributes_only_trajectory_and_strike_negative():
    torch.manual_seed(1)
    rows = 3
    outputs = {
        "trajectory": torch.randn(rows, 2, 2, requires_grad=True),
        "strike": torch.randn(rows, requires_grad=True),
        "tti": torch.randn(rows, 1, requires_grad=True),
        "zone": torch.randn(rows, 4, requires_grad=True),
        "position": torch.randn(rows, 2, requires_grad=True),
        "intensity": torch.randn(rows, requires_grad=True),
    }
    impact = torch.tensor([True, True, False])  # row 2: labelled negative, no impact within H_max
    nan = float("nan")
    losses = [
        trajectory_loss(
            outputs["trajectory"], torch.zeros(rows, 2, 2), torch.ones(rows, 2, dtype=torch.bool)
        ),
        auxiliary_loss(outputs["strike"], torch.tensor([1.0, 1.0, 0.0]), torch.ones(rows, dtype=torch.bool)),
        tti_loss(outputs["tti"], torch.tensor([0.05, 0.2, nan]), impact, mode="direct", h_max_s=0.3),
        zone_loss(outputs["zone"], torch.tensor([1, 2, 0]), impact),
        masked_regression(outputs["position"], torch.tensor([[0.1, 0.1], [0.0, 0.2], [nan, nan]]), impact),
        masked_regression(outputs["intensity"], torch.tensor([1.0, 2.0, nan]), impact),
    ]
    sum(losses).backward()
    assert all(torch.isfinite(v) for v in losses)
    for task in ("tti", "zone", "position", "intensity"):
        assert not outputs[task].grad[2].abs().sum(), task  # no imputed target, no gradient
        assert outputs[task].grad[:2].abs().sum() > 0, task
    assert outputs["strike"].grad[2] > 0  # pushed towards a negative
    assert outputs["trajectory"].grad[2].abs().sum() > 0
    empty = torch.zeros(rows, dtype=torch.bool)
    assert float(zone_loss(outputs["zone"], torch.tensor([1, 2, 0]), empty)) == 0
    assert float(tti_loss(outputs["tti"], torch.full((rows,), nan), empty, mode="log", h_max_s=0.3)) == 0


@pytest.mark.parametrize("mode", ["direct", "log", "bins"])
def test_tti_parameterisations_train_and_decode_inside_h_max(mode):
    torch.manual_seed(2)
    width = 6 if mode == "bins" else 1
    output = torch.randn(4, width, requires_grad=True)
    target = torch.tensor([0.01, 0.1, 0.25, 0.3])
    loss = tti_loss(output, target, torch.ones(4, dtype=torch.bool), mode=mode, h_max_s=0.3)
    loss.backward()
    assert torch.isfinite(loss) and output.grad.abs().sum() > 0
    decoded = decode_tti(output.detach() * 20, mode=mode, h_max_s=0.3)
    assert decoded.shape == (4,) and (decoded >= 0).all() and (decoded <= 0.3 + 1e-6).all()
    with pytest.raises(ValueError, match="H_max"):
        tti_loss(
            output,
            torch.tensor([0.1, 0.2, 0.31, 0.1]),
            torch.ones(4, dtype=torch.bool),
            mode=mode,
            h_max_s=0.3,
        )


def test_weighting_schemes():
    losses = {"trajectory": torch.tensor(2.0), "zone": torch.tensor(4.0)}
    tasks = ("trajectory", "strike", "zone")
    assert float(TaskWeighting(tasks, "fixed")(losses)) == 6.0
    assert float(TaskWeighting(tasks, "fixed", lambdas={"zone": 0.5})(losses)) == 4.0
    assert float(TaskWeighting(tasks, "trajectory_dominant", dominant_lambda=0.25)(losses)) == 3.0
    uncertainty = TaskWeighting(tasks, "uncertainty")
    with torch.no_grad():
        uncertainty.log_vars.copy_(torch.tensor([0.0, 5.0, 1.0]))
    # The absent strike task contributes neither loss nor its regulariser s_t.
    expected = 2.0 + (4.0 * torch.exp(torch.tensor(-1.0)) + 1.0)
    torch.testing.assert_close(uncertainty(losses), expected)
    gradnorm = TaskWeighting(tasks, "gradnorm")
    gradnorm({k: v.clone().requires_grad_(True) for k, v in losses.items()}).backward()
    assert gradnorm.weights.grad is None  # only the GradNorm balance step moves these weights
    with torch.no_grad():
        gradnorm.weights.copy_(torch.tensor([4.0, 1.0, 1.0]))
    gradnorm.renormalise()
    torch.testing.assert_close(gradnorm.weights.sum(), torch.tensor(3.0))
    for bad in (
        dict(scheme="softmax"),
        dict(scheme="fixed", lambdas={"force": 1.0}),
        dict(scheme="fixed", lambdas={"zone": -1.0}),
    ):
        with pytest.raises(ValueError):
            TaskWeighting(tasks, **bad)
    with pytest.raises(ValueError, match="trajectory"):
        TaskWeighting(("strike", "zone"), "trajectory_dominant")
    with pytest.raises(ValueError, match="no labelled task"):
        TaskWeighting(tasks, "fixed")({})
