"""Verify a local package before the app constructs its runtime or feature stream.

Runtime and feature construction live in app: prediction never imports geometry.
The pinned manifest binds the export, schema, normalization and training provenance.
"""

import hashlib
import json
import math
from pathlib import Path


def file_hash(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_package(cfg, schema):
    ant, settings = cfg["anticipator"], cfg["anticipator"]["model"]
    directory = Path(settings["path"])
    manifest_path = directory / "manifest.json"
    if file_hash(manifest_path) != settings["manifest_hash"]:
        raise ValueError("model manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if settings["runtime"] != "torchscript":
        raise ValueError("only verified TorchScript packages are supported")
    if "mt_config" in manifest or "extension" in manifest:
        raise ValueError("unadopted extension/multi-task package is not a Phase 10 live package")
    expected = {
        "family": settings["family"],
        "N": settings["N"],
        "K": ant["K"],
        "F": schema.dimension,
        "feature_schema_id": settings["feature_schema_id"],
        "feature_schema_hash": schema.fingerprint,
        "export_hash": settings["hash"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"model {key} mismatch")
    if not math.isclose(manifest["dt_step"], ant["dt_step_s"], rel_tol=0, abs_tol=1e-12):
        raise ValueError("model dt_step mismatch")
    if not math.isclose(1 / cfg["camera_profile"]["requested_fps"], manifest["dt_step"], abs_tol=1e-6):
        raise ValueError("capture FPS / training dt_step mismatch; resampling is not enabled")
    if cfg["tracking"]["history_n"] < manifest["N"]:
        raise ValueError("tracking history is shorter than model N")
    if schema.feature_schema_id != manifest["feature_schema_id"]:
        raise ValueError("feature schema id mismatch")
    if file_hash(directory / "export.pt") != settings["hash"]:
        raise ValueError("model export hash mismatch")
    if file_hash(settings["norm_stats_path"]) != manifest["norm_stats_id"]:
        raise ValueError("normalization hash mismatch")
    stats = json.loads(Path(settings["norm_stats_path"]).read_text(encoding="utf-8"))
    for key in (
        "fold",
        "dataset_version",
        "dataset_hash",
        "split_hash",
        "feature_schema_id",
        "feature_schema_hash",
    ):
        if stats.get(key) != manifest.get(key):
            raise ValueError(f"normalization {key} mismatch")
    if not manifest.get("model_id"):
        raise ValueError("model_id missing")
    return directory, manifest, stats
