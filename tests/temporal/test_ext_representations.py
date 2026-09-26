"""Phase 12 representations and decoding: round trips, mixture head/loss, layouts, adapters, and the
trajectory-first route of every extension through the unchanged harness (SYNTHETIC)."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import torch
from ext_helpers import controlled, ext_config, manifest
from mt_helpers import track

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.contracts import Anticipator, CandidateDerivation
from spacedrums.contracts.schema import validate
from spacedrums.eval.probabilistic import AnchorRecorder, calibration
from spacedrums.eval.replay import replay
from spacedrums.features.batch import build_features
from spacedrums.features.schema import FeatureSchema
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.probabilistic import CrossingProbabilityGate, sample_trajectories
from spacedrums.models.temporal.ext import ExtensionConfig, build_extension_model
from spacedrums.models.temporal.ext.adapter import EnsembleAnticipator, ExtensionAnticipator, decode_extension
from spacedrums.models.temporal.ext.decoding import bounded_acceleration, fit_acceleration_bound
from spacedrums.models.temporal.ext.representations import (
    IncrementHead,
    MixtureHead,
    PolynomialHead,
    mixture_loss,
    mixture_parts,
)
from spacedrums.models.temporal.ext.uncertainty import gaussian_nll, member_rows, mixture_rows, sigma_rows

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "configs/prototype.candidate.yaml")
REGISTRY = ZoneRegistry.from_config(CFG["zones"])
SCHEMA = FeatureSchema(CFG["zones"])


def test_config_enforces_one_declared_extension_and_hashes():
    base = ExtensionConfig("gru", 56)
    assert (
        base.is_reference
        and base.extensions == ()
        and base.offsets_s == pytest.approx((1 / 30, 2 / 30, 0.1, 4 / 30))
    )
    two = ExtensionConfig("gru", 56, k=3, steps=(1, 2, 4))
    assert two.extensions == ("E1-two-rate",) and two.max_step == 4 and not two.uniform
    assert ExtensionConfig("gru", 56, k=3, steps=(1, 2, 3)).uniform
    assert ExtensionConfig.from_dict(two.to_dict()) == two and two.config_hash != base.config_hash
    with pytest.raises(ValueError, match="one extension"):
        ExtensionConfig("tt", 56, representation="velocity")
    with pytest.raises(ValueError, match="mixture needs"):
        ExtensionConfig("gru", 56, representation="mixture")
    with pytest.raises(ValueError, match="residual"):
        ExtensionConfig("gru", 56, residual="cv", residual_features=(10,))
    with pytest.raises(ValueError, match="strictly increasing"):
        ExtensionConfig("gru", 56, k=3, steps=(1, 3, 2))
    with pytest.raises(ValueError, match="receptive"):
        ExtensionConfig("tcn", 56, n=64)
    assert ExtensionConfig.from_reference(base.encoder_config.to_dict()) == base


def test_increment_and_polynomial_heads_round_trip():
    torch.manual_seed(1)
    offsets = (0.02, 0.04, 0.08)
    h = torch.randn(5, 8)
    inc = IncrementHead(8, offsets)
    point, velocity = inc(h)
    intervals = torch.tensor([0.02, 0.02, 0.04]).reshape(1, 3, 1)
    torch.testing.assert_close(torch.cumsum(velocity.reshape(5, 3, 2) * intervals, 1), point)
    poly = PolynomialHead(8, offsets, 3)
    point, velocity = poly(h)
    c = poly.coefficients(h).reshape(5, 2, 3).detach()
    for j, tau in enumerate(offsets):
        u = tau / 0.08
        expected = sum(c[:, :, d] * u ** (d + 1) for d in range(3))
        derivative = sum(c[:, :, d] * (d + 1) * u**d / 0.08 for d in range(3))
        torch.testing.assert_close(point[:, j], expected)
        torch.testing.assert_close(velocity.reshape(5, 3, 2)[:, j], derivative)


def test_mixture_head_picks_the_most_probable_mode_and_loss_is_relaxed_wta():
    torch.manual_seed(2)
    head = MixtureHead(8, 3, 2)
    h = torch.randn(6, 8)
    point, aux = head(h)
    logits, trajectories = mixture_parts(aux, modes=2, k=3)
    torch.testing.assert_close(point, trajectories[torch.arange(6), logits.argmax(1)])
    assert torch.allclose(torch.softmax(logits, -1).sum(-1), torch.ones(6))
    # Mode 0 exact, mode 1 far: the winner gets 1 - eps, the other eps / (M - 1).
    target = torch.zeros(1, 3, 2)
    modes = torch.stack((torch.zeros(3, 2), torch.ones(3, 2)))[None]
    aux = torch.cat((torch.tensor([[0.0, 0.0]]), modes.reshape(1, -1)), 1).requires_grad_(True)
    mask = torch.ones(1, 3, dtype=torch.bool)
    loss = mixture_loss(aux, target, mask, modes=2, k=3, kind="l1", epsilon=0.1, mode_weight=1.0)
    ce = torch.nn.functional.cross_entropy(torch.zeros(1, 2), torch.tensor([0]))
    assert float(loss.detach()) == pytest.approx(0.1 * 1.0 + float(ce))
    loss.backward()
    assert float(aux.grad[0, 2:8].abs().sum()) == 0  # the exact winner has zero error gradient
    assert float(aux.grad[0, 8:].abs().sum()) > 0  # the loser still learns (relaxed)
    nan_target = torch.full((1, 3, 2), float("nan"))
    empty = mixture_loss(aux, nan_target, torch.zeros(1, 3, dtype=torch.bool), modes=2, k=3)
    assert float(empty.detach()) == 0


def test_gaussian_nll_masks_and_detaches_the_mean():
    mean = torch.zeros(2, 2, 2, requires_grad=True)
    log_sigma = torch.zeros(2, 4, requires_grad=True)
    target = torch.tensor([[[1.0, 0.0], [float("nan"), 0.0]], [[0.0, 0.0], [0.0, 0.0]]])
    mask = torch.tensor([[True, False], [True, True]])
    loss = gaussian_nll(mean.detach(), log_sigma, target, mask)
    loss.backward()
    assert torch.isfinite(loss) and mean.grad is None and torch.isfinite(log_sigma.grad).all()
    assert float(loss.detach()) == pytest.approx(0.5 * 1.0 / 6)
    assert float(gaussian_nll(mean, log_sigma, target, torch.zeros_like(mask)).detach()) == 0


def test_bounded_acceleration_projection_and_train_only_bound():
    offsets = (0.02, 0.04, 0.06, 0.08)
    smooth = np.array([[0.0, 0.01], [0.0, 0.02], [0.0, 0.03], [0.0, 0.04]])
    np.testing.assert_allclose(bounded_acceleration(smooth, offsets, 1.0), smooth, atol=1e-12)
    jerky = np.array([[0.0, 0.01], [0.0, 0.05], [0.0, 0.0], [0.0, 0.06]])
    out = bounded_acceleration(jerky, offsets, 10.0)
    np.testing.assert_allclose(out[0], jerky[0])  # the first step is free
    points = np.vstack((np.zeros(2), out))
    second = (points[2:] - 2 * points[1:-1] + points[:-2]) / 0.02**2
    assert np.hypot(*second.T).max() <= 10.0 + 1e-9
    targets = np.stack([smooth, jerky])
    mask = np.array([[True] * 4, [True, True, False, False]])
    bound = fit_acceleration_bound(targets, mask, offsets, quantile=1.0)
    assert bound == pytest.approx(np.hypot(0.0, (0.05 - 2 * 0.01) / 0.02**2))
    with pytest.raises(ValueError, match="two consecutive"):
        fit_acceleration_bound(targets[:, :1], mask[:, :1], offsets[:1])


def test_layout_rows_round_trip_through_probabilistic_geometry():
    point = np.array([[0.0, 0.05], [0.0, 0.1]])
    tip = (0.4, 0.5)
    t = track(3, tip[1])
    config = ext_config("ref", k=2)
    members = np.stack((point + 0.01, point - 0.01, point))
    pred = decode_extension(
        t, point, np.zeros(1), config, anticipator_id="x", model_hash=None,
        uncertainty=member_rows(point, members), kind="members_xy",
    )  # fmt: skip
    paths = sample_trajectories(pred, tip)
    np.testing.assert_allclose(
        [[q.position for q in path[1:]] for _, path in paths], members + tip, atol=1e-12
    )
    logits, modes = np.array([0.0, np.log(3.0)]), np.stack((point, -point))
    rows = mixture_rows(-point, logits, modes)
    weights = [
        w for w, _ in sample_trajectories(replace(pred, uncertainty=rows, uncertainty_kind="mixture_xy"), tip)
    ]
    assert weights == pytest.approx([0.25, 0.75])
    sigma = sigma_rows(np.log([0.1, 0.2, 0.3, 0.4]), 2)
    np.testing.assert_allclose(sigma, [[0.1, 0.2], [0.3, 0.4]])


def test_decode_emits_offsets_velocities_and_layouts():
    t = track(2, 0.5)
    two = ext_config("two-rate")
    pred = decode_extension(t, np.zeros((3, 2)), np.zeros(1), two, anticipator_id="x", model_hash=None)
    assert pred.t_offsets_s == pytest.approx((0.02, 0.04, 0.08)) and pred.sample_times()[-1] == pytest.approx(
        t.t_capture + 0.08
    )
    vel = ext_config("velocity")
    pred = decode_extension(t, np.zeros((4, 2)), np.arange(8.0), vel, anticipator_id="x", model_hash=None)
    assert pred.velocities == ((0.0, 1.0), (2.0, 3.0), (4.0, 5.0), (6.0, 7.0)) and pred.t_offsets_s is None
    gauss = ext_config("gaussian")
    pred = decode_extension(
        t, np.zeros((4, 2)), np.log(np.full(8, 0.01)), gauss, anticipator_id="x", model_hash=None
    )
    assert pred.uncertainty_kind == "sigma_xy" and pred.uncertainty[0] == pytest.approx((0.01, 0.01))
    validate("trajectory-prediction", pred.to_dict())
    with pytest.raises(ValueError, match="finite"):
        decode_extension(t, np.full((4, 2), np.nan), np.zeros(1), gauss, anticipator_id="x", model_hash=None)


def _run(tracks, model_fn, arm="MODEL:C-GRU", gate=None, p_commit=0.0):
    return replay(
        tracks,
        arm=arm,
        registry=REGISTRY,
        commit_settings=replace(CommitSettings.from_config(CFG), p_commit=p_commit, n_confirm_frames=0),
        v_min=0.15,
        session_id="synthetic-ext-route",
        model=model_fn,
        feature_schema=SCHEMA,
        feature_window_n=2,
        feature_records=build_features(tracks, SCHEMA),
        candidate_gate=gate,
    )


@pytest.mark.parametrize("variant", ["ref", "gaussian", "mixture", "tt"])
@pytest.mark.parametrize("crossing", [False, True])
def test_every_extension_commits_only_through_geometry(variant, crossing):
    config = ext_config(variant)
    arm = "MODEL:C-TT" if config.family == "tt" else "MODEL:C-GRU"
    model = controlled(config, crossing=crossing) if variant != "tt" else _controlled_tt(config, crossing)
    adapter = ExtensionAnticipator(model, manifest(config))
    assert isinstance(adapter, Anticipator)
    tracks = [track(i, 0.505 + i * 0.02) for i in range(8)]
    result = _run(tracks, adapter, arm=arm)
    assert bool(result.committed) == crossing
    ids = {c.candidate_id for c in result.candidates}
    for c in result.candidates:
        assert c.derivation is CandidateDerivation.GEOMETRY and c.strike_probability is None
    for s in result.committed:
        validate("committed-strike", s.to_dict())
        assert s.candidate_id in ids and s.arm == ("C-TT" if variant == "tt" else "C-GRU")
    for p in result.predictions:
        validate("trajectory-prediction", p.to_dict())
    if crossing:  # future frames cannot change earlier commits
        changed = tracks[:4] + [track(i, 0.3) for i in range(4, 8)]
        again = _controlled_tt(config, True) if variant == "tt" else controlled(config)
        future = _run(changed, ExtensionAnticipator(again, manifest(config)), arm=arm)
        early = [s.to_dict() for s in result.committed if s.frame_id < 4]
        assert early == [s.to_dict() for s in future.committed if s.frame_id < 4]


def _controlled_tt(config, crossing):
    model = build_extension_model(config).eval()
    step = torch.cat([torch.tensor([0.0, 0.05 * (1 if crossing else -1) * (j + 1)]) for j in range(config.k)])
    with torch.no_grad():
        model.head.trajectory.weight.zero_()
        model.head.trajectory.bias.copy_(step)
    return model


def test_crossing_gate_relabels_and_p_commit_gates_through_the_unchanged_policy():
    config = ext_config("gaussian")
    tracks = [track(i, 0.505 + i * 0.02) for i in range(8)]
    results = {}
    for p_commit in (0.0, 0.999):
        recorder = AnchorRecorder(ExtensionAnticipator(controlled(config, sigma=0.3), manifest(config)))
        gate = CrossingProbabilityGate(REGISTRY, v_min=0.15, anchor_of=recorder.anchor, samples=64)
        results[p_commit] = _run(tracks, recorder, gate=gate, p_commit=p_commit)
        probabilities = [entry["strike_probability"] for entry in gate.log]
        assert probabilities and all(0 < p < 0.999 for p in probabilities)
    plain = _run(tracks, ExtensionAnticipator(controlled(config, sigma=0.3), manifest(config)))

    def strip(rows):
        return [replace(s, strike_probability=None).to_dict() for s in rows]

    assert strip(results[0.0].candidates) == strip(plain.candidates)
    assert [s.frame_id for s in results[0.0].committed] == [s.frame_id for s in plain.committed]
    assert plain.committed and not results[0.999].committed


def test_ensemble_adapter_means_members_and_reports_spread():
    config = ext_config("ref")
    members = [controlled(config), controlled(config, crossing=False)]
    ensemble = EnsembleAnticipator(members, [manifest(config, seed=s, checkpoint=str(s)) for s in (1, 2)])
    tracks = [track(i, 0.505 + i * 0.02) for i in range(3)]
    pred = ensemble.predict(tracks[:2], build_arrays(tracks[:2]))
    np.testing.assert_allclose(np.asarray(pred.positions), np.array([tracks[1].tip_filtered] * 4), atol=1e-6)
    assert pred.uncertainty_kind == "members_xy" and len(pred.uncertainty[0]) == 4
    with pytest.raises(ValueError, match="share"):
        EnsembleAnticipator(members, [manifest(config), manifest(config, fold=1)])


def build_arrays(tracks):
    from spacedrums.features.streaming import history_arrays

    x, m = history_arrays(build_features(tracks, SCHEMA), SCHEMA)
    return x, m


def test_calibration_metrics():
    report = calibration([0.05, 0.15, 0.95, 0.85], [0, 0, 1, 1], bins=10)
    assert report["roc_auc"] == 1.0 and report["brier"] == pytest.approx(
        (0.05**2 + 0.15**2 + 0.05**2 + 0.15**2) / 4
    )
    assert report["ece"] == pytest.approx(0.1)
    with pytest.raises(ValueError, match="binary"):
        calibration([0.2], [2])
