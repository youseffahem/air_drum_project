"""Load and run a fold's LightGBM heads with batch-one inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np


class GBDTPredictor:
    def __init__(self, directory: str | Path):
        directory = Path(directory)
        self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.models = {}
        for name, expected in self.manifest["model_hashes"].items():
            path = directory / f"{name}.txt"
            actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"model hash mismatch: {name}")
            self.models[name] = lgb.Booster(model_file=str(path))
        digest = hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest()
        self.model_hash = "sha256:" + digest

    def predict(self, x: np.ndarray, mask: np.ndarray) -> dict:
        shape = tuple(self.manifest["feature_shape"])
        if x.shape != shape or mask.shape != shape:
            raise ValueError(f"expected one window of shape {shape}")
        row = np.concatenate((x.ravel(), mask.ravel().astype(float)))[None, :]

        def head(name):
            model = self.models.get(name)
            return None if model is None else model.predict(row, num_threads=1)[0]

        p = float(head("strike"))
        zone_ids = self.manifest["zone_ids"]
        if "zone" in self.models:
            z = head("zone")
            index = int(float(z) >= 0.5) if len(zone_ids) == 2 else int(np.argmax(z))
            zone = zone_ids[index]
        else:
            zone = zone_ids[0] if len(zone_ids) == 1 else None
        points = {}
        for step in self.manifest["displacement_steps"]:
            dx, dy = head(f"displacement_{step}_0"), head(f"displacement_{step}_1")
            if dx is not None and dy is not None:
                points[int(step)] = (float(dx), float(dy))
        return {
            "strike_probability": p,
            "tti": None if "tti" not in self.models else float(head("tti")),
            "zone_id": zone,
            "displacements": points,
        }
