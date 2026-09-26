"""Extension Anticipators: the Phase 10 causal guards and windowing, extension-aware decoding.

Every output is a ``TrajectoryPrediction`` whose ``positions`` are the point trajectory (mean or
most probable mode); ``velocities``, ``t_offsets_s`` and the reserved ``uncertainty`` layouts carry
the extension's extra information. No path returns a strike: geometry decides (ADR-0007).
"""

import hashlib

import numpy as np
import torch

from spacedrums.contracts import TrajectoryAux, TrajectoryPrediction

from ..adapter import TemporalAnticipator
from .config import ExtensionConfig
from .decoding import bounded_acceleration
from .representations import mixture_parts
from .uncertainty import member_rows, mixture_rows, sigma_rows


def decode_extension(
    track, point, aux, config, *, anticipator_id, model_hash, a_max=None, uncertainty=None, kind=None
):
    """Displacements (+ layout rows) of one frame become a time-stamped absolute trajectory."""
    point = np.asarray(point, dtype=float)
    aux = np.asarray(aux, dtype=float)
    if point.shape != (config.k, 2) or not np.isfinite(point).all() or not np.isfinite(aux).all():
        raise ValueError("finite [K,2] point trajectory required")
    if track.tip_filtered is None:
        raise ValueError("current tip required")
    if a_max is not None:
        point = bounded_acceleration(point, config.offsets_s, a_max)
    velocities = None
    if config.representation in ("velocity", "polynomial"):
        velocities = tuple(map(tuple, aux.reshape(config.k, 2)))
    if uncertainty is None:
        if config.uncertainty == "gaussian":
            uncertainty, kind = sigma_rows(aux, config.k), "sigma_xy"
        elif config.representation == "mixture":
            logits, trajectories = mixture_parts(torch.as_tensor(aux)[None], modes=config.modes, k=config.k)
            uncertainty = mixture_rows(point, logits[0].numpy(), trajectories[0].numpy())
            kind = "mixture_xy"
    positions = point + np.asarray(track.tip_filtered)
    return TrajectoryPrediction(
        frame_id=track.frame_id,
        t_capture=track.t_capture,
        hand_id=track.hand_id,
        anticipator_id=anticipator_id,
        model_hash=model_hash,
        K=config.k,
        dt_step=config.dt_step,
        t_offsets_s=None if config.uniform else config.offsets_s,
        positions=tuple(map(tuple, positions)),
        velocities=velocities,
        uncertainty=uncertainty,
        uncertainty_kind=kind,
        aux=TrajectoryAux(),
        t_inference_done=track.t_capture,
    )


def extension_config(manifest):
    if "ext_config" in manifest:
        return ExtensionConfig.from_dict(manifest["ext_config"])
    return ExtensionConfig.from_reference(manifest["config"])


class ExtensionAnticipator(TemporalAnticipator):
    """Windowed Anticipator for an extension package, or a Phase 10 package with E5(b) smoothing."""

    def __init__(self, model, manifest, *, variant=None, a_max=None, **kwargs):
        if kwargs.get("stateful"):
            raise ValueError("extension adapters are windowed; the bounded GRU cache is Phase 10 only")
        super().__init__(model, manifest, **kwargs)
        self.config = extension_config(manifest)
        if a_max is not None and (not a_max > 0 or self.config.extensions):
            raise ValueError("E5(b) smoothing needs a positive a_max and a plain displacement model")
        self.a_max = a_max
        self.variant = variant or manifest.get("variant", "ref")
        self.anticipator_id = f"temporal-ext-{self.variant}-{manifest['family']}-v1"

    def _decode(self, track, outputs):
        point, aux = outputs
        return decode_extension(
            track,
            point[0].numpy(),
            aux[0].numpy(),
            self.config,
            anticipator_id=self.anticipator_id,
            model_hash=self.model_hash,
            a_max=self.a_max,
        )


class EnsembleAnticipator(TemporalAnticipator):
    """E4(b): same-fold seed ensemble; point = member mean, ``members_xy`` carries the spread."""

    def __init__(self, models, manifests, *, variant="e4-ens3", **kwargs):
        if len(models) != len(manifests) or len(models) < 2:
            raise ValueError("an ensemble needs at least two models with manifests")
        keys = ("N", "K", "F", "dt_step", "family", "fold", "feature_schema_hash", "norm_stats_id")
        if any(any(m[key] != manifests[0][key] for key in keys) for m in manifests[1:]):
            raise ValueError("ensemble members must share N/K/F/dt, family, fold, schema and statistics")
        if kwargs.get("stateful"):
            raise ValueError("the ensemble adapter is windowed")
        super().__init__(models[0], manifests[0], **kwargs)
        self.models = [m.eval() for m in models]
        self.config = extension_config(manifests[0])
        hashes = sorted(m.get("export_hash", m["checkpoint_hash"]) for m in manifests)
        self.model_hash = "sha256:" + hashlib.sha256("|".join(hashes).encode()).hexdigest()
        self.variant = variant
        self.anticipator_id = f"temporal-ext-{variant}-{manifests[0]['family']}-v1"

    def _infer(self, hand, x, mask):
        del hand
        return [model(x[None], mask[None]) for model in self.models]

    def _decode(self, track, outputs):
        members = np.stack([o[0][0].numpy().astype(float) for o in outputs])
        point = members.mean(axis=0)
        return decode_extension(
            track,
            point,
            np.zeros(1),
            self.config,
            anticipator_id=self.anticipator_id,
            model_hash=self.model_hash,
            uncertainty=member_rows(point, members),
            kind="members_xy",
        )
