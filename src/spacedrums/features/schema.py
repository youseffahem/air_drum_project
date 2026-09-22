"""fs-v1 semantic descriptor, exact ordering and record envelope."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from spacedrums.config import config_hash
from spacedrums.features.groups import DEFAULT_GROUPS, GROUPS, ROBUST_GROUPS
from spacedrums.geometry.zones import ZoneRegistry


@dataclass(frozen=True)
class KinematicFeatures:
    frame_id: int
    t_capture: float
    hand_id: str
    feature_schema_id: str
    values: tuple[float, ...]
    mask: tuple[bool, ...]
    dt: float
    track_status: str

    def __post_init__(self):
        if len(self.values) != len(self.mask) or not all(math.isfinite(x) for x in self.values):
            raise ValueError("feature values must be finite and match mask length")
        if self.dt < 0 or not math.isfinite(self.dt):
            raise ValueError("invalid dt")
        if any(v != 0 for v, m in zip(self.values, self.mask, strict=True) if not m):
            raise ValueError("masked features must be zero")

    def to_dict(self):
        d = asdict(self)
        return {"schema_version": "1.0", **d, "values": list(self.values), "mask": list(self.mask)}


class FeatureSchema:
    feature_schema_id = "fs-v1"

    def __init__(self, zones, *, groups=DEFAULT_GROUPS, tts_clip_s=2.0, epsilon=1e-6):
        # JSON config is copied; callers cannot mutate the schema through their input.
        import copy

        self.zones_config = copy.deepcopy(list(zones))
        self.zones = tuple(ZoneRegistry.from_config(self.zones_config))
        self.groups = tuple(g for g in GROUPS if g in groups)
        if set(groups) - set(GROUPS) or not self.groups:
            raise ValueError("invalid feature groups")
        if not math.isfinite(tts_clip_s) or tts_clip_s <= 0 or not math.isfinite(epsilon) or epsilon <= 0:
            raise ValueError("clip and epsilon must be finite positive values")
        self.tts_clip_s, self.epsilon = float(tts_clip_s), float(epsilon)
        self.fields = []

        def add(name, group, unit, derivation, mask="live", bounds=None, scaling=None):
            if group not in self.groups:
                return
            self.fields.append(
                {
                    "name": name,
                    "group": group,
                    "unit": unit,
                    "derivation": derivation,
                    "mask_rule": "INVALID/STALE: zero and masked; otherwise " + mask,
                    "range": bounds or [None, None],
                    "normalization": scaling or ("robust" if group in ROBUST_GROUPS else "zscore"),
                }
            )

        for axis in "xy":
            add(f"tip_{axis}", "POS", "roi_norm", "TrackState.tip_filtered")
        for z in self.zones:
            for axis in "xy":
                add(f"relative_{z.zone_id}_{axis}", "POS", "roi_norm", "tip - impact surface midpoint")
        for name in ("vx", "vy", "speed", "direction_x", "direction_y", "vertical_velocity"):
            direction = name.startswith("direction")
            add(
                name,
                "VEL",
                "unitless" if direction else "roi_norm/s",
                "filter velocity; speed=hypot(v); direction=v/speed; vertical_velocity=vy",
                "speed > epsilon" if direction else "live",
                [-1, 1] if direction else None,
                "identity" if direction else None,
            )
        for z in self.zones:
            add(f"inward_{z.zone_id}", "VEL", "roi_norm/s", "dot(filter velocity, zone inward normal)")
        for name in ("ax", "ay", "acceleration", "acc_tangent", "acc_normal"):
            add(
                name,
                "ACC",
                "roi_norm/s^2",
                "filter acceleration, else backward velocity difference / dt",
                "acceleration available; decomposition additionally requires nonzero speed",
            )
        for name in ("jx", "jy", "jerk"):
            add(
                name,
                "JERK",
                "roi_norm/s^3",
                "backward acceleration difference / actual dt",
                "two consecutive accelerations, at most three TrackStates",
            )
        for name, unit in (
            ("axis_sin", "unitless"),
            ("axis_cos", "unitless"),
            ("axis_omega", "rad/s"),
            ("axis_confidence", "unitless"),
            ("stick_length", "roi_norm"),
        ):
            add(
                name,
                "AXIS",
                unit,
                "filtered axis; same-frame StickObservation confidence/length",
                "source field available; omega backward wrapped difference if filter lacks it",
                [-1, 1] if name in ("axis_sin", "axis_cos") else None,
                "identity" if name in ("axis_sin", "axis_cos", "axis_confidence") else None,
            )
        for idx in (0, 5, 9, 4):
            for axis in "xy":
                add(
                    f"landmark_{idx}_{axis}",
                    "HAND",
                    "hand_size",
                    "(landmark - wrist) / distance(wrist,middle MCP)",
                    "same-frame hand present and hand size > epsilon; landmark visibility > 0 if supplied",
                )
        for name in ("bbox_width", "bbox_height", "handedness_score"):
            add(
                name,
                "HAND",
                "unitless" if name == "handedness_score" else "roi_norm",
                "same-frame HandObservation",
                "hand present",
            )
        for z in self.zones:
            add(
                f"distance_{z.zone_id}",
                "ZONE",
                "roi_norm",
                "dot(closest point on finite impact surface - tip, inward normal)",
            )
            add(
                f"tts_{z.zone_id}",
                "ZONE",
                "s",
                "clip(distance/max(inward speed,epsilon),0,tts_clip_s)",
                "live",
                [0, self.tts_clip_s],
            )
        for name in ("valid", "degraded", "tip_confidence", "frames_since_valid", "dropped_since_last"):
            add(
                name,
                "CONF",
                "frames" if name in ("frames_since_valid", "dropped_since_last") else "unitless",
                "TrackState status/confidence/age; same-frame FrameSample drops",
                "source available",
                [0, None],
                "identity",
            )
        add(
            "dt",
            "TIME",
            "s",
            "current - previous processed per-hand t_capture",
            "previous frame exists",
            [0, None],
            "identity",
        )
        add(
            "window_elapsed",
            "TIME",
            "s",
            "window assembler: t_j - first history t_capture",
            "masked in standalone per-frame record; filled in assembled history only",
            [0, None],
            "identity",
        )
        self.names = tuple(f["name"] for f in self.fields)
        self.index = {name: i for i, name in enumerate(self.names)}
        self.fingerprint = config_hash(self.descriptor())

    @property
    def dimension(self):
        return len(self.fields)

    def descriptor(self):
        return {
            "feature_schema_id": self.feature_schema_id,
            "schema_version": "1.0",
            "groups": list(self.groups),
            "dimension": len(self.fields),
            "fields": self.fields,
            "zone_layout": self.zones_config,
            "tts_clip_s": self.tts_clip_s,
            "epsilon": self.epsilon,
            "core_history_n": 3 if "JERK" in self.groups else 2,
            "group_dimensions": {g: sum(f["group"] == g for f in self.fields) for g in self.groups},
        }
