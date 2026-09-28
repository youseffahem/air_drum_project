"""Causal ablation transforms, applied identically during training and replay."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

import numpy as np

from spacedrums.config import config_hash
from spacedrums.features.groups import group_indices
from spacedrums.models.temporal.config import MultiTaskConfig
from spacedrums.models.temporal.consistency import AuxHeadSettings

MASK_GROUPS = {
    "AB-VEL": ("VEL",),
    "AB-ACC": ("ACC", "JERK"),
    "AB-AXIS": ("AXIS",),
    "AB-HAND": ("HAND",),
    "AB-ZONE": ("ZONE",),
    "AB-CONF": ("CONF",),
}


def mask_spec(schema, ablation_id):
    """Retain F; remove explicit redundant cues as well as the named group.

    Positions may still imply motion and upstream tracking still uses hand/axis information.
    This tests explicit model inputs, not statistical independence from the removed signal.
    """
    if ablation_id not in MASK_GROUPS:
        raise ValueError("unknown feature ablation")
    indices = set(group_indices(schema, MASK_GROUPS[ablation_id]))
    for i, name in enumerate(schema.names):
        if ablation_id == "AB-VEL" and (name.startswith("tts_") or name in ("acc_tangent", "acc_normal")):
            indices.add(i)
        if ablation_id == "AB-ZONE" and name.startswith(("relative_", "inward_")):
            indices.add(i)
    spec = {
        "ablation_id": ablation_id,
        "feature_schema_hash": schema.fingerprint,
        "dimension": schema.dimension,
        "indices": sorted(indices),
        "names": [schema.names[i] for i in sorted(indices)],
        "method": "zero values and masks AFTER train-fold normalization; retain architecture",
    }
    return {**spec, "sha256": config_hash(spec)}


def mask_normalized(values, masks, spec):
    x, m = np.array(values, copy=True), np.array(masks, dtype=bool, copy=True)
    if x.shape != m.shape or x.ndim < 1 or x.shape[-1] != spec["dimension"]:
        raise ValueError("mask tensor shape differs from recorded feature layout")
    if not np.isfinite(x).all():
        raise ValueError("nonfinite normalized input")
    x[..., spec["indices"]], m[..., spec["indices"]] = 0, False
    x[~m] = 0
    return x, m


class MaskedAdapter:
    """The existing replay normalizes once; this wrapper masks that normalized window."""

    def __init__(self, adapter, schema, spec):
        if spec["feature_schema_hash"] != schema.fingerprint:
            raise ValueError("mask schema fingerprint mismatch")
        self.adapter, self.spec = adapter, spec
        self.diagnostic_only = getattr(adapter, "diagnostic_only", False)

    def __call__(self, track, history, window):
        transformed = None if window is None else mask_normalized(*window, self.spec)
        return self.adapter(track, history, transformed)

    def reset(self, reason=None):
        self.adapter.reset(reason)


def drop_frames(frames: Iterable, *, factor: int, origin_frame_id: int):
    """Drop whole source frames BEFORE perception/tracking; preserve stamps and ids.

    A fixed source-frame origin makes truncation/prefix replay deterministic. Existing source
    gaps are not filled. A (30, 2) declaration means 30 -> 15 downsampling, never native 60 FPS.
    The iterable contains FrameSample or (FrameSample, payload) pairs; payloads are untouched.
    """
    if type(factor) is not int or factor < 2 or type(origin_frame_id) is not int:
        raise ValueError("integer factor >= 2 and an explicit source origin required")
    previous = None
    for item in frames:
        frame = item[0] if isinstance(item, tuple) else item
        if frame.frame_id < origin_frame_id or (
            previous is not None
            and (frame.frame_id <= previous.frame_id or frame.t_capture <= previous.t_capture)
        ):
            raise ValueError("source frames must increase from the declared origin")
        previous = frame
        if (frame.frame_id - origin_frame_id) % factor == 0:
            yield item


def model_variant(reference, variant, gate=None):
    """One declared factor only; windows/targets must subsequently be rebuilt for N/K changes."""
    aid, changes = variant["ablation_id"], variant["changes"]
    base = reference.base if isinstance(reference, MultiTaskConfig) else reference
    gate = gate or AuxHeadSettings()
    if aid.startswith("AB-HIST-"):
        base = replace(base, n=changes["n"])
    elif aid.startswith("AB-HOR-"):
        base = replace(base, k=changes["k"])
    if isinstance(reference, MultiTaskConfig):
        heads = reference.heads
        if aid == "AB-NOTRAJ":
            if not {"trajectory", "strike", "tti", "zone"} <= set(heads):
                raise ValueError("AB-NOTRAJ requires the existing trajectory/strike/TTI/zone heads")
            heads = tuple(h for h in heads if h != "trajectory")
        if aid == "AB-INT":
            if "intensity" not in heads:
                raise ValueError("AB-INT requires an intensity head")
            heads = tuple(h for h in heads if h != "intensity")
            checks = tuple(c for c in gate.agreement_checks if c != "intensity")
            gate = replace(
                gate,
                intensity_source="geometry",
                use_agreement=gate.use_agreement and bool(checks),
                agreement_checks=checks or ("zone", "tti", "position"),
            )
        if aid == "AB-AUX":
            if "strike" not in heads:
                raise ValueError("AB-AUX requires a strike head")
            heads = tuple(h for h in heads if h != "strike")
            gate = replace(gate, use_p_aux=False, use_agreement=False)
        return replace(reference, base=base, heads=heads), gate
    if aid in ("AB-NOTRAJ", "AB-INT"):
        raise ValueError(f"{aid} requires a multi-task reference")
    if aid == "AB-AUX":
        if not base.auxiliary:
            raise ValueError("AB-AUX requires a trained auxiliary head")
        base = replace(base, auxiliary=False)
    return base, gate


def reusable_horizon(previous, requested):
    """Reuse only an identical, complete cell signature; no path-only or K-only match."""
    required = {
        "dataset",
        "labels",
        "split",
        "norm",
        "features",
        "model_config",
        "training",
        "seed",
        "fold",
        "harness",
        "w_s",
        "delay",
        "operating_rule",
        "budget",
        "sources",
    }
    return set(previous) == required and set(requested) == required and previous == requested
