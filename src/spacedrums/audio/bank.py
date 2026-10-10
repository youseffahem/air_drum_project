"""Manifest-verified local WAV sample bank with deterministic resampling."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


@dataclass(frozen=True)
class Sample:
    sample_id: str
    data: np.ndarray
    sample_rate_hz: int
    source_path: Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


LAYERS = ("hard", "soft")  # preference order: ``bank[group]`` falls back to the first hard take


class SampleBank:
    """Hash-verified samples. Optional ``groups`` map a group id (what a zone names) to velocity
    layers, each an ordered tuple of round-robin takes; a plain manifest has none and is unchanged."""

    def __init__(
        self,
        samples: dict[str, Sample],
        sample_rate_hz: int,
        groups: dict[str, dict[str, tuple[Sample, ...]]] | None = None,
    ) -> None:
        if not samples:
            raise ValueError("sample bank must not be empty")
        self.samples = dict(samples)
        self.sample_rate_hz = int(sample_rate_hz)
        self.groups = {g: dict(layers) for g, layers in (groups or {}).items()}

    def __getitem__(self, sample_id: str) -> Sample:
        if sample_id in self.samples:
            return self.samples[sample_id]
        layers = self.groups[sample_id]  # KeyError for an unknown id, as before
        return layers[next(layer for layer in LAYERS if layer in layers)][0]

    @classmethod
    def load(cls, root: str | Path, manifest: str | Path, *, sample_rate_hz: int) -> SampleBank:
        root, manifest = Path(root), Path(manifest)
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        loaded: dict[str, Sample] = {}
        takes: dict[str, dict[str, dict[int, Sample]]] = {}
        for entry in doc["samples"]:
            sample_id = str(entry["sample_id"])
            if sample_id in loaded:
                raise ValueError(f"duplicate sample_id {sample_id}")
            path = root / entry["file"]
            actual = _sha256(path)
            expected = str(entry["sha256"]).removeprefix("sha256:")
            if actual != expected:
                raise ValueError(f"sample hash mismatch for {sample_id}")
            data, source_rate = sf.read(path, dtype="float32", always_2d=True)
            data = np.mean(data, axis=1, dtype=np.float32)
            if source_rate != sample_rate_hz:
                divisor = math.gcd(int(source_rate), int(sample_rate_hz))
                data = resample_poly(data, sample_rate_hz // divisor, source_rate // divisor).astype(
                    np.float32
                )
            if not np.isfinite(data).all() or len(data) == 0:
                raise ValueError(f"invalid audio in {sample_id}")
            loaded[sample_id] = Sample(sample_id, data, sample_rate_hz, path)
            if "group" in entry:
                group, layer, robin = str(entry["group"]), str(entry["layer"]), int(entry["round_robin"])
                if layer not in LAYERS or group in loaded:
                    raise ValueError(f"invalid layer or group id for {sample_id}")
                if robin in takes.setdefault(group, {}).setdefault(layer, {}):
                    raise ValueError(f"duplicate round robin {robin} for {group}/{layer}")
                takes[group][layer][robin] = loaded[sample_id]
        groups = {}
        for group, layers in takes.items():
            if "hard" not in layers:
                raise ValueError(f"group {group} needs a hard layer")
            groups[group] = {layer: tuple(t[k] for k in sorted(t)) for layer, t in layers.items()}
        return cls(loaded, sample_rate_hz, groups)


__all__ = ["Sample", "SampleBank"]
