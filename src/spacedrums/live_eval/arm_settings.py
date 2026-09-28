"""ADR-0036: exact offline-to-live arm settings; no value selection or live evidence."""

from dataclasses import asdict, replace
from pathlib import Path

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.prediction import RuleSettings


def locked_arm_settings(offline, cfg, arm_ids):
    """Resolve defaults exactly as Phase 18 Arm.settings/build_arm do."""
    specs = {a["arm_id"]: a for a in offline["arms"]}
    if set(arm_ids) != {"A", "B", "C"}:
        raise ValueError("live arm mapping must be exactly A/B/C")
    if arm_ids["B"] != offline["b_primary"] or arm_ids["C"] != offline["c_primary"]:
        raise ValueError("live B/C must name offline b_primary/c_primary")
    if specs[arm_ids["A"]]["replay_arm"] != "A":
        raise ValueError("live A must name the offline Phase 05 reference")
    if specs[arm_ids["C"]]["replay_arm"] not in ("MODEL:C-GRU", "MODEL:C-TCN"):
        raise ValueError("this live runtime supports trajectory GRU/TCN only; adoption pending")
    output = {}
    for label, aid in arm_ids.items():
        spec = specs[aid]
        controls = dict(spec["controls"])
        speed = controls.pop("v_min")
        output[label] = {
            "commit": asdict(replace(CommitSettings.from_config(cfg), **controls)),
            "v_min": speed,
        }
        if label == "B":
            output[label]["rule"] = asdict(replace(RuleSettings.from_config(cfg), **spec["rule"]))
    return output


def consistency_errors(offline, offline_cfg, live_cfg, arm_ids):
    try:
        expected = locked_arm_settings(offline, offline_cfg, arm_ids)
    except (ValueError, KeyError, TypeError) as exc:
        return [str(exc)]
    actual = live_cfg.get("live_arm_settings")
    if actual is None:
        return ["live config requires explicit per-arm settings (ADR-0036)"]
    errors = [
        f"live {arm} settings differ from archived offline arm"
        for arm in "ABC"
        if actual[arm] != expected[arm]
    ]
    model = next(a for a in offline["arms"] if a["arm_id"] == offline["c_primary"])["model"]
    configured = live_cfg["anticipator"].get("model") or {}
    if (
        configured.get("manifest_hash") != model["manifest_sha256"]
        or configured.get("hash") != model["export_sha256"]
    ):
        errors.append("live model manifest/export pins differ from offline primary")
    return errors


def live_binding_errors(live, *, root=None):
    """Check pinned input bytes before a live lock can be archived or verified."""
    import json

    from .prereg import file_digest, lock_digest, lock_errors

    root = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    try:
        paths = {}
        for name in ("config", "offline_config", "offline_lock"):
            path = root / live[f"{name}_path"]
            if not path.is_file():
                return [f"missing live-lock dependency: {name}"]
            if name != "offline_lock" and file_digest(path) != live[f"{name}_sha256"]:
                return [f"live-lock {name} hash mismatch"]
            paths[name] = path
        lock = json.loads(paths["offline_lock"].read_text(encoding="utf-8"))
        if lock.get("lock_kind") != "offline":
            return ["live lock must refer to an offline lock"]
        if lock_digest(lock) != live["offline_lock_sha256"]:
            return ["live-lock offline lock digest mismatch"]
        errors = lock_errors(lock)
        if errors:
            return ["invalid offline lock: " + "; ".join(errors)]
        offline_cfg = load_config(paths["offline_config"]).data
        live_cfg = load_config(paths["config"]).data
        # Phase 18 currently evaluates this fixed base config. Its bytes must be in the source freeze.
        frozen_cfg = lock["offline"]["sources"].get("configs/prototype.candidate.yaml")
        if frozen_cfg != live["offline_config_sha256"]:
            return ["offline base configuration is absent from or differs from the offline source freeze"]
        return consistency_errors(lock["offline"], offline_cfg, live_cfg, live["arms"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"invalid live arm binding: {exc}"]
