"""Closed Phase 19 plan validation; no participant defaults or implicit reference."""

import copy
import math

import yaml

from spacedrums.contracts.schema import validate
from spacedrums.models.temporal.config import MultiTaskConfig, TemporalConfig
from spacedrums.models.temporal.consistency import AuxHeadSettings
from spacedrums.models.temporal.train import TrainConfig

from .transforms import MASK_GROUPS, model_variant

VARIANTS = (
    *MASK_GROUPS,
    "AB-HIST-S",
    "AB-HIST-L",
    "AB-HOR-S",
    "AB-HOR-L",
    "AB-NOTRAJ",
    "AB-REACT",
    "AB-RULE",
    "AB-INT",
    "AB-FPS",
    "AB-TIP",
    "AB-AUX",
)


def model_config(plan):
    data = plan["reference"]["model"]
    return MultiTaskConfig.from_dict(data) if "base" in data else TemporalConfig(**data)


def validate_plan(plan):
    validate("ablation-plan", plan)
    config = model_config(plan)
    base = config.base if isinstance(config, MultiTaskConfig) else config
    TrainConfig(**plan["reference"]["training"])
    gate = AuxHeadSettings(**plan["reference"]["gate"])
    ids = [v["ablation_id"] for v in plan["variants"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ablation id")
    for variant in plan["variants"]:
        aid, change = variant["ablation_id"], variant["changes"]
        if aid.startswith("AB-HIST-"):
            n = change["n"]
            if not ((aid.endswith("-S") and n < base.n) or (aid.endswith("-L") and n > base.n)):
                raise ValueError("history direction must differ from reference N")
        if aid.startswith("AB-HOR-"):
            k = change["k"]
            if not ((aid.endswith("-S") and k < base.k) or (aid.endswith("-L") and k > base.k)):
                raise ValueError("horizon direction must differ from reference K")
        if aid == "AB-FPS":
            if (change["source_fps"], change["target_fps"]) not in ((30, 15), (60, 30)):
                raise ValueError("FPS must be honest 30 -> 15 or evidenced native 60 -> 30 frame dropping")
        if aid not in ("AB-FPS", "AB-TIP", "AB-REACT", "AB-RULE"):
            model_variant(config, variant, gate)
    if plan["evidence"] == "SYNTHETIC/DEV" and plan["frozen_reference"] is not None:
        raise ValueError("synthetic plan cannot name a participant frozen reference")

    def finite(value):
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return not isinstance(value, float) or math.isfinite(value)

    if not finite(plan):
        raise ValueError("nonfinite plan value")
    return copy.deepcopy(plan)


def read_plan(path):
    with open(path, encoding="utf-8") as fh:
        return validate_plan(yaml.safe_load(fh))
