"""Build and load extension models over the unchanged Phase 10 encoders (or the E3 encoder)."""

import json
from pathlib import Path

import torch

from ..data import sha
from ..gru import GRUPredictor
from ..tcn import TCNPredictor
from .config import ExtensionConfig
from .decoding import ResidualExtrapolation
from .representations import DisplacementHead, IncrementHead, MixtureHead, PolynomialHead
from .tiny_transformer import TinyTransformerPredictor
from .uncertainty import GaussianHead


def make_head(config):
    if config.uncertainty == "gaussian":
        return GaussianHead(config.hidden, config.k)
    if config.representation == "velocity":
        return IncrementHead(config.hidden, config.offsets_s)
    if config.representation == "polynomial":
        return PolynomialHead(config.hidden, config.offsets_s, config.degree)
    if config.representation == "mixture":
        return MixtureHead(config.hidden, config.k, config.modes)
    return DisplacementHead(config.hidden, config.k)


def build_extension_model(config, *, residual_center=None, residual_scale=None):
    """Encoder first, then head (Phase 10 parameter order); E5 wraps the whole predictor."""

    def factory():
        return make_head(config)

    if config.family == "gru":
        inner = GRUPredictor(config.encoder_config, head_factory=factory)
    elif config.family == "tcn":
        inner = TCNPredictor(config.encoder_config, head_factory=factory)
    else:
        inner = TinyTransformerPredictor(config, head_factory=factory)
    if config.residual:
        return ResidualExtrapolation(inner, config, residual_center, residual_scale)
    return inner


def load_extension_model(directory, *, exported=True):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    config = ExtensionConfig.from_dict(manifest["ext_config"])
    if config.config_hash != manifest["config_hash"]:
        raise ValueError("configuration hash mismatch")
    expected = {
        "N": config.n,
        "K": config.k,
        "F": config.features,
        "dt_step": config.dt_step,
        "family": config.family,
        "offsets_s": list(config.offsets_s),
        "extensions": list(config.extensions),
    }
    if any(manifest[key] != value for key, value in expected.items()):
        raise ValueError("manifest dimensions differ from hashed configuration")
    filename, key = ("export.pt", "export_hash") if exported else ("checkpoint.pt", "checkpoint_hash")
    if sha(directory / filename) != manifest[key]:
        raise ValueError("model content hash mismatch")
    if exported:
        model = torch.jit.load(str(directory / filename), map_location="cpu")
    else:
        model = build_extension_model(config)
        model.load_state_dict(torch.load(directory / filename, weights_only=True, map_location="cpu"))
    return model.eval(), manifest
