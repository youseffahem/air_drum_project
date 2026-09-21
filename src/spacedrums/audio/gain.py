"""Configurable monotone kinematic-intensity-proxy to linear-gain mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GainCurve:
    gain_curve_id: str
    kind: str
    proxy_min: float
    proxy_max: float
    gain_min: float
    gain_max: float
    exponent: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in ("LINEAR_CLIPPED", "POWER"):
            raise ValueError("gain kind must be LINEAR_CLIPPED or POWER")
        if self.proxy_max <= self.proxy_min or self.gain_min < 0 or self.gain_max < self.gain_min:
            raise ValueError("gain bounds must be ordered and gains non-negative")
        if self.exponent <= 0:
            raise ValueError("gain exponent must be positive")

    def __call__(self, intensity_proxy: float) -> float:
        """Map a kinematic proxy (not force) monotonically to linear gain."""
        x = min(self.proxy_max, max(self.proxy_min, float(intensity_proxy)))
        unit = (x - self.proxy_min) / (self.proxy_max - self.proxy_min)
        if self.kind == "POWER":
            unit **= self.exponent
        return self.gain_min + unit * (self.gain_max - self.gain_min)

    @classmethod
    def from_config(cls, data: dict) -> GainCurve:
        return cls(
            gain_curve_id=str(data["gain_curve_id"]),
            kind=str(data["type"]),
            proxy_min=float(data["proxy_min"]),
            proxy_max=float(data["proxy_max"]),
            gain_min=float(data["gain_min"]),
            gain_max=float(data["gain_max"]),
            exponent=float(data.get("exponent", 1.0)),
        )


__all__ = ["GainCurve"]
