"""Explicit, hashable candidate settings; no participant-selected defaults."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TemporalConfig:
    family: str
    features: int
    n: int = 8
    k: int = 4
    dt_step: float = 1 / 30
    hidden: int = 24
    layers: int = 1
    dropout: float = 0.0
    kernel: int = 3
    dilations: tuple[int, ...] = (1, 2, 4)
    auxiliary: bool = False

    def __post_init__(self):
        if self.family not in ("gru", "tcn"):
            raise ValueError("family must be gru or tcn")
        if any(
            type(v) is not int or v < 1 for v in (self.features, self.n, self.k, self.hidden, self.layers)
        ):
            raise ValueError("dimensions must be positive integers")
        if not math.isfinite(self.dt_step) or self.dt_step <= 0 or not 0 <= self.dropout < 1:
            raise ValueError("invalid time step/dropout")
        if self.kernel < 2 or not self.dilations or any(type(d) is not int or d < 1 for d in self.dilations):
            raise ValueError("invalid causal convolution settings")
        if self.family == "tcn" and self.receptive_field < self.n:
            raise ValueError("TCN receptive field must cover N")

    @property
    def receptive_field(self):
        return 1 + 2 * (self.kernel - 1) * sum(self.dilations)

    def to_dict(self):
        return asdict(self)

    @property
    def config_hash(self):
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def build_model(config):
    from .gru import GRUPredictor
    from .tcn import TCNPredictor

    return (GRUPredictor if config.family == "gru" else TCNPredictor)(config)
