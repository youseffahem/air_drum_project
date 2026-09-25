"""Explicit, hashable candidate settings; no participant-selected defaults."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass

TASKS = ("trajectory", "strike", "tti", "zone", "position", "intensity")
TTI_MODES = ("direct", "log", "bins")


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


@dataclass(frozen=True)
class MultiTaskConfig:
    """Phase 10 encoder settings plus the declared Phase 11 heads over one shared encoder.

    ``base.auxiliary`` stays False: the strike head is a Phase 11 head, not the Phase 10 logit.
    A configuration without the trajectory head exists only for the labelled no-trajectory
    diagnostic and is never live eligible (ADR-0007 amendment).
    """

    base: TemporalConfig
    heads: tuple[str, ...] = TASKS
    zone_ids: tuple[str, ...] = ()
    tti_mode: str = "direct"
    tti_bins: int = 8
    h_max_s: float = 0.3
    head_hidden: int = 0

    def __post_init__(self):
        if isinstance(self.base, dict):
            base = dict(self.base)
            base["dilations"] = tuple(base.get("dilations", (1, 2, 4)))
            object.__setattr__(self, "base", TemporalConfig(**base))
        heads = tuple(self.heads)
        if not heads or len(set(heads)) != len(heads) or any(h not in TASKS for h in heads):
            raise ValueError(f"heads must be a nonempty unique subset of {TASKS}")
        # Canonical order keeps the configuration hash independent of listing order.
        object.__setattr__(self, "heads", tuple(t for t in TASKS if t in heads))
        object.__setattr__(self, "zone_ids", tuple(str(z) for z in self.zone_ids))
        if self.base.auxiliary:
            raise ValueError("multi-task models use the strike head, not the Phase 10 auxiliary logit")
        if ("zone" in self.heads) != bool(self.zone_ids) or len(set(self.zone_ids)) != len(self.zone_ids):
            raise ValueError("zone head requires unique declared zone ids, and only then")
        if self.tti_mode not in TTI_MODES or type(self.tti_bins) is not int or self.tti_bins < 2:
            raise ValueError("invalid TTI parameterisation")
        horizon = self.base.k * self.base.dt_step
        if not math.isfinite(self.h_max_s) or self.h_max_s + 1e-9 < horizon:
            raise ValueError("H_max must be finite and at least the trajectory horizon K * dt_step")
        if type(self.head_hidden) is not int or self.head_hidden < 0:
            raise ValueError("head_hidden must be a nonnegative integer")

    @property
    def family(self):
        return self.base.family

    @property
    def has_trajectory(self):
        return "trajectory" in self.heads

    @property
    def live_eligible(self):
        # Trajectory first: a package without the trajectory head can only feed the diagnostic.
        return self.has_trajectory

    @property
    def tti_width(self):
        return self.tti_bins if self.tti_mode == "bins" else 1

    def to_dict(self):
        return {
            "base": self.base.to_dict(),
            "heads": list(self.heads),
            "zone_ids": list(self.zone_ids),
            "tti_mode": self.tti_mode,
            "tti_bins": self.tti_bins,
            "h_max_s": self.h_max_s,
            "head_hidden": self.head_hidden,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "heads": tuple(data["heads"]), "zone_ids": tuple(data["zone_ids"])})

    @property
    def config_hash(self):
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def build_model(config):
    from .gru import GRUPredictor
    from .tcn import TCNPredictor

    return (GRUPredictor if config.family == "gru" else TCNPredictor)(config)


def build_mt_model(config):
    from .gru import MultiTaskGRU
    from .tcn import MultiTaskTCN

    return (MultiTaskGRU if config.family == "gru" else MultiTaskTCN)(config)
