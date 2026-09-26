"""Phase 12 extension settings. One structural extension per model unless explicitly combined.

Candidate values only; nothing here is adopted. The Phase 10 encoders are reused unchanged, so a
configuration without any extension describes the Phase 10 trajectory predictor exactly.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass

from ..config import TemporalConfig

FAMILIES = ("gru", "tcn", "tt")
REPRESENTATIONS = ("displacement", "velocity", "polynomial", "mixture")
UNCERTAINTIES = ("gaussian",)
RESIDUALS = ("cv", "ca")


@dataclass(frozen=True)
class DataView:
    """The fields ``data.read_samples``/``load_fold`` read; K is the densest target step needed."""

    n: int
    features: int
    k: int
    dt_step: float
    auxiliary: bool = False


@dataclass(frozen=True)
class ExtensionConfig:
    family: str
    features: int
    n: int = 8
    k: int = 4
    dt_step: float = 1 / 30
    steps: tuple[int, ...] | None = None
    hidden: int = 16
    layers: int = 1
    dropout: float = 0.0
    kernel: int = 3
    dilations: tuple[int, ...] = (1, 2, 4)
    attention_heads: int = 2
    feedforward: int = 32
    representation: str = "displacement"
    degree: int = 3
    modes: int = 1
    wta_epsilon: float = 0.05
    mode_weight: float = 0.5
    uncertainty: str | None = None
    residual: str | None = None
    residual_features: tuple[int, ...] = ()
    combination: bool = False

    def __post_init__(self):
        object.__setattr__(self, "dilations", tuple(self.dilations))
        object.__setattr__(self, "residual_features", tuple(self.residual_features))
        if self.steps is not None:
            object.__setattr__(self, "steps", tuple(self.steps))
        if self.family not in FAMILIES:
            raise ValueError(f"family must be one of {FAMILIES}")
        if any(
            type(v) is not int or v < 1 for v in (self.features, self.n, self.k, self.hidden, self.layers)
        ):
            raise ValueError("dimensions must be positive integers")
        if not math.isfinite(self.dt_step) or self.dt_step <= 0 or not 0 <= self.dropout < 1:
            raise ValueError("invalid time step/dropout")
        if self.steps is not None and (
            len(self.steps) != self.k
            or any(type(s) is not int or s < 1 for s in self.steps)
            or any(b <= a for a, b in zip(self.steps, self.steps[1:], strict=False))
        ):
            raise ValueError("steps must be K strictly increasing positive integers")
        if self.representation not in REPRESENTATIONS:
            raise ValueError(f"representation must be one of {REPRESENTATIONS}")
        if (self.representation == "mixture") != (type(self.modes) is int and self.modes >= 2):
            raise ValueError("a mixture needs at least two modes, every other representation exactly one")
        if self.representation != "mixture" and self.modes != 1:
            raise ValueError("modes must be 1 outside a mixture")
        if type(self.degree) is not int or not 1 <= self.degree <= 5:
            raise ValueError("polynomial degree must be an integer in [1, 5]")
        if not 0 <= self.wta_epsilon < 1 or not math.isfinite(self.mode_weight) or self.mode_weight < 0:
            raise ValueError("invalid mixture loss settings")
        if self.uncertainty is not None and self.uncertainty not in UNCERTAINTIES:
            raise ValueError(f"uncertainty must be null or one of {UNCERTAINTIES}")
        if self.uncertainty is not None and self.representation != "displacement":
            raise ValueError("a Gaussian head is declared only over displacements")
        if self.residual is not None and self.residual not in RESIDUALS:
            raise ValueError(f"residual must be null or one of {RESIDUALS}")
        width = {"cv": 2, "ca": 4}.get(self.residual, 0)
        if (
            len(self.residual_features) != width
            or len(set(self.residual_features)) != width
            or any(type(i) is not int or not 0 <= i < self.features for i in self.residual_features)
        ):
            raise ValueError(
                "residual extrapolation needs distinct velocity (and acceleration) feature indices"
            )
        if self.family == "tt":
            if self.hidden % self.attention_heads or self.feedforward < 1:
                raise ValueError("TT width must divide by the head count; feed-forward width positive")
        else:
            _ = self.encoder_config  # delegates GRU/TCN validation, incl. the TCN receptive field
        if len(self.extensions) > 1 and not self.combination:
            raise ValueError("one extension per model; combinations only after individual adoption")

    @property
    def extensions(self):
        """Structural extensions (E1 two-rate grid, E2, E3, E4, E5). K alone is a Phase 10 parameter."""
        found = []
        if not self.uniform:
            found.append("E1-two-rate")
        if self.representation != "displacement":
            found.append("E2-" + self.representation)
        if self.family == "tt":
            found.append("E3-tiny-transformer")
        if self.uncertainty:
            found.append("E4-" + self.uncertainty)
        if self.residual:
            found.append("E5-residual-" + self.residual)
        return tuple(found)

    @property
    def grid_steps(self):
        return self.steps if self.steps is not None else tuple(range(1, self.k + 1))

    @property
    def uniform(self):
        return self.grid_steps == tuple(range(1, self.k + 1))

    @property
    def max_step(self):
        return self.grid_steps[-1]

    @property
    def offsets_s(self):
        return tuple(s * self.dt_step for s in self.grid_steps)

    @property
    def horizon_s(self):
        return self.max_step * self.dt_step

    @property
    def encoder_config(self):
        """The Phase 10 encoder settings; K here only sizes the unused Phase 10 default head."""
        return TemporalConfig(
            self.family,
            self.features,
            n=self.n,
            k=self.k,
            dt_step=self.dt_step,
            hidden=self.hidden,
            layers=self.layers,
            dropout=self.dropout,
            kernel=self.kernel,
            dilations=self.dilations,
        )

    @property
    def data_view(self):
        return DataView(self.n, self.features, self.max_step, self.dt_step)

    @property
    def aux_width(self):
        if self.representation in ("velocity", "polynomial") or self.uncertainty == "gaussian":
            return 2 * self.k
        if self.representation == "mixture":
            return self.modes + self.modes * self.k * 2
        return 1

    @property
    def uncertainty_kind(self):
        if self.uncertainty == "gaussian":
            return "sigma_xy"
        return "mixture_xy" if self.representation == "mixture" else None

    @property
    def is_reference(self):
        return not self.extensions

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        for key in ("dilations", "residual_features", "steps"):
            if data.get(key) is not None:
                data[key] = tuple(data[key])
        return cls(**data)

    @classmethod
    def from_reference(cls, temporal):
        """The extension-framework description of a Phase 10 configuration (no extension)."""
        if isinstance(temporal, dict):
            temporal = TemporalConfig(
                **{**temporal, "dilations": tuple(temporal.get("dilations", (1, 2, 4)))}
            )
        if temporal.auxiliary:
            raise ValueError("extensions are compared against the pure-trajectory Phase 10 model")
        return cls(
            temporal.family,
            temporal.features,
            n=temporal.n,
            k=temporal.k,
            dt_step=temporal.dt_step,
            hidden=temporal.hidden,
            layers=temporal.layers,
            dropout=temporal.dropout,
            kernel=temporal.kernel,
            dilations=temporal.dilations,
        )

    @property
    def config_hash(self):
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
