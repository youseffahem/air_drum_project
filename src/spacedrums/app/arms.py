"""App-level model assembly and explicit runtime arm switching."""

import numpy as np

from spacedrums.config import config_hash
from spacedrums.contracts import Arm
from spacedrums.features.normalize import NormStats
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.prediction.model_arm import ModelArm
from spacedrums.prediction.model_loader import verify_package

MODEL_ARMS = (Arm.C_GRU, Arm.C_TCN)


def layout_structure(schema):
    """The feature descriptor without zone geometry: names, order, units, groups and zone ids."""
    d = {k: v for k, v in schema.descriptor().items() if k != "zone_layout"}
    d["zone_ids"] = [z.zone_id for z in schema.zones]
    return d


class LayoutAdaptedStats:
    """Training-fold statistics applied to features computed from calibrated zones (Phase 14, ADR-0037).

    The statistics stay bound to the training layout's fingerprint (verified with the package).
    A calibrated layout keeps every feature name, order, unit and group - only zone geometry moves -
    so the per-index statistics apply unchanged. Every call asserts that the features being
    normalised came from the calibrated (loaded) schema: ZONE features never silently use the
    recording layout. Whether the model generalises to a moved layout is untested (ADR-0037).
    """

    def __init__(self, stats, *, training, runtime):
        if layout_structure(training) != layout_structure(runtime):
            raise ValueError("calibrated layout changes the feature structure (zone ids/order)")
        self.stats, self.training, self.runtime = stats, training, runtime
        self.data = stats.data

    def apply(self, values, mask, schema):
        if schema is not self.runtime:
            raise AssertionError("ZONE features must be computed from the loaded calibration's zones")
        return self.stats.apply(values, mask, self.training)


def build_model_arm(cfg, *, clock):
    # Lazy: A/B-only application startup does not load PyTorch.
    import torch

    from spacedrums.models.temporal.adapter import TemporalAnticipator
    from spacedrums.models.temporal.export import load_model

    f = cfg["features"]
    options = {"groups": f["groups"], "epsilon": f["epsilon"], "tts_clip_s": f["tts_clip_s"]}
    # Runtime features always come from the loaded zones (calibrated when a calibration is applied);
    # the package is verified against the layout it was trained with (the calibration template).
    schema = FeatureSchema(cfg["zones"], **options)
    calib = cfg.get("calibration")
    training = FeatureSchema(calib["template_zones"], **options) if calib else schema
    try:
        directory, manifest, stats_data = verify_package(cfg, training)
    except ValueError as exc:
        if calib and "mismatch" in str(exc):
            raise ValueError(
                f"{exc} (calibration template {calib['template_layout_id']!r}: the package must have been "
                "trained on this layout)"
            ) from exc
        raise
    stats = NormStats(stats_data)
    stats.apply(np.zeros((1, training.dimension)), np.ones((1, training.dimension), bool), training)
    if training.fingerprint != schema.fingerprint:
        stats = LayoutAdaptedStats(stats, training=training, runtime=schema)
    torch.set_num_threads(cfg["anticipator"]["model"]["intra_op_threads"])
    model, loaded_manifest = load_model(directory)
    if manifest != loaded_manifest:
        raise ValueError("manifest changed while loading")
    return ModelArm(
        TemporalAnticipator(model, manifest),
        StreamingFeatures(schema, history_n=manifest["N"]),
        stats,
        clock=clock,
    )


def check_zone_features(model_arm, cfg):
    """Task 14.7 runtime assertion: the model's zone-relative features use the loaded zones.

    Returns the provenance recorded in the session (feature layout hash, training layout, fit).
    """
    schema = model_arm.stream.schema
    if schema.zones_config != list(cfg["zones"]):
        raise AssertionError("model features were built from zones other than the loaded configuration's")
    calib = cfg.get("calibration")
    feature_hash = config_hash(schema.zones_config)
    if calib is not None and feature_hash != calib["zones_hash"]:
        raise AssertionError("model features do not use the applied calibration's zones")
    adapted = isinstance(model_arm.stats, LayoutAdaptedStats)
    return {
        "feature_zones_hash": feature_hash,
        "training_layout": calib["template_layout_id"] if calib else "configured zones",
        "training_zones_hash": calib["template_zones_hash"] if calib else feature_hash,
        "layout_adapted": adapted,
        "fit": calib["fit"] if calib else None,
        "caution": (
            "features follow the calibrated zones; model behaviour on a layout that departs from its "
            "training layout is untested (ADR-0037)"
            if adapted
            else None
        ),
    }


class ArmSwitch:
    def __init__(self, available, active):
        self.available = tuple(Arm(a) for a in available)
        self.active = Arm(active)
        if self.active not in self.available:
            raise ValueError("active arm is not available")
        self.events = []

    def select(self, arm, t):
        arm = Arm(arm)
        if arm not in self.available:
            raise ValueError(f"arm {arm} is not running")
        if arm == self.active:
            return False
        self.events.append({"t": t, "from": str(self.active), "to": str(arm)})
        self.active = arm
        return True
