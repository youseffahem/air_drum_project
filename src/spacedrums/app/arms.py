"""App-level model assembly and explicit runtime arm switching."""

import numpy as np

from spacedrums.contracts import Arm
from spacedrums.features.normalize import NormStats
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import StreamingFeatures
from spacedrums.prediction.model_arm import ModelArm
from spacedrums.prediction.model_loader import verify_package

MODEL_ARMS = (Arm.C_GRU, Arm.C_TCN)


def build_model_arm(cfg, *, clock):
    # Lazy: A/B-only application startup does not load PyTorch.
    import torch

    from spacedrums.models.temporal.adapter import TemporalAnticipator
    from spacedrums.models.temporal.export import load_model

    f = cfg["features"]
    schema = FeatureSchema(cfg["zones"], groups=f["groups"], epsilon=f["epsilon"], tts_clip_s=f["tts_clip_s"])
    directory, manifest, stats_data = verify_package(cfg, schema)
    stats = NormStats(stats_data)
    stats.apply(np.zeros((1, schema.dimension)), np.ones((1, schema.dimension), bool), schema)
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
