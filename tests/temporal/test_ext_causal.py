"""TEST-CAUSAL-1/2 for every Phase 12 encoder, head and decoder (README section 13).

Future frames beyond the current one never change an output; only the last N frames matter;
masked NaN payloads have no influence; attention never looks at a later position; the E5 residual
base reads the current frame only. Negative controls show the tests can fail.
"""

import pytest
import torch
from ext_helpers import VARIANT_KWARGS, ext_config

from spacedrums.models.temporal.ext import build_extension_model
from spacedrums.models.temporal.ext.attention import CausalSelfAttention

VARIANTS = sorted(VARIANT_KWARGS)


def _outputs_equal(a, b):
    for x, y in zip(a, b, strict=True):
        torch.testing.assert_close(x, y, atol=0, rtol=0)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("family", ["gru", "tcn"])
def test_causal_future_perturbation_truncation_and_masked_payload(variant, family):
    torch.manual_seed(3)
    config = ext_config(variant, family, n=4, k=VARIANT_KWARGS[variant].get("k", 3))
    model = build_extension_model(config).eval()
    x = torch.randn(2, 13, 56)
    mask = torch.rand_like(x) > 0.2
    mask[:, :, 10:12] = True  # residual velocity features present on every frame
    changed = x.clone()
    changed[:, 8:] += 1000.0
    with torch.no_grad():
        # TEST-CAUSAL-1: frames after the current frame (index 7) cannot matter.
        _outputs_equal(model(x[:, :8], mask[:, :8]), model(changed[:, :8], mask[:, :8]))
        # TEST-CAUSAL-2: only the declared last N frames matter.
        _outputs_equal(model(x[:, :8], mask[:, :8]), model(x[:, 4:8], mask[:, 4:8]))
        poisoned = x.clone()
        poisoned[~mask] = float("nan")
        _outputs_equal(model(x, mask), model(poisoned, mask))
        # Negative control: the current frame does matter.
        moved = x.clone()
        moved[:, 7] += 1.0
        assert not torch.equal(model(x[:, :8], mask[:, :8])[0], model(moved[:, :8], mask[:, :8])[0])


def test_attention_masks_every_future_position():
    torch.manual_seed(4)
    layer = CausalSelfAttention(8, 2, 6).eval()
    x = torch.randn(3, 6, 8)
    with torch.no_grad():
        reference = layer(x)
        for j in range(6):
            perturbed = x.clone()
            perturbed[:, j] += 100.0
            out = layer(perturbed)
            # Positions before j never see j; position j itself does (negative control).
            torch.testing.assert_close(out[:, :j], reference[:, :j], atol=0, rtol=0)
            assert not torch.allclose(out[:, j], reference[:, j])
    # A shorter window uses the same relative bias and mask (right-aligned current frame).
    with torch.no_grad():
        torch.testing.assert_close(layer(x[:, :4]), reference[:, :4], atol=1e-6, rtol=1e-5)
    with pytest.raises(ValueError, match="longer than"):
        layer(torch.randn(1, 7, 8))


def test_tiny_transformer_every_position_is_causal_inside_the_window():
    torch.manual_seed(5)
    config = ext_config("tt", n=6)
    model = build_extension_model(config).eval()
    x, mask = torch.randn(2, 6, 56), torch.rand(2, 6, 56) > 0.1
    with torch.no_grad():
        reference = model.encode(x, mask)
        for j in range(6):
            perturbed = x.clone()
            perturbed[:, j] += 50.0
            torch.testing.assert_close(model.encode(perturbed, mask)[:, :j], reference[:, :j], atol=0, rtol=0)


@pytest.mark.parametrize("variant", ["residual-cv", "residual-ca"])
def test_residual_base_reads_only_the_current_frame(variant):
    config = ext_config(variant, "tcn", n=4)
    model = build_extension_model(
        config,
        residual_center=[0.1] * len(config.residual_features),
        residual_scale=[2.0] * len(config.residual_features),
    ).eval()
    x, mask = torch.randn(2, 4, 56), torch.ones(2, 4, 56, dtype=torch.bool)
    earlier = x.clone()
    earlier[:, :3] += 7.0
    torch.testing.assert_close(model.base(x, mask), model.base(earlier, mask), atol=0, rtol=0)
    masked = mask.clone()
    masked[:, -1, [10, 20]] = False  # x velocity (and x acceleration) absent on the current frame
    base = model.base(x, masked)
    assert torch.equal(base[..., 0], torch.zeros_like(base[..., 0]))
    assert not torch.equal(base[..., 1], torch.zeros_like(base[..., 1]))
