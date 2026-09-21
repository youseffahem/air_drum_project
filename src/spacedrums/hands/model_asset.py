"""Locate and hash-verify the landmark model file pinned in ``assets/models/manifest.json``.

docs/environment.md section 7: models are downloaded once (``scripts/fetch_hand_landmarker_model.py``),
stored under ``assets/`` with a SHA-256 in a manifest, and loaded from disk. This module is the
load-side half of that rule: it refuses a missing or tampered file instead of silently running a
different model than the one every run log cites (``detector_id`` embeds the hash prefix).

Location rule mirrors ``spacedrums.contracts.schema.repo_root``: the repository root relative to
this source tree, overridable with ``SPACEDRUMS_ASSETS_ROOT`` for a non-editable deployment.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from spacedrums.contracts.schema import repo_root

_ENV = "SPACEDRUMS_ASSETS_ROOT"
MANIFEST_NAME = "manifest.json"


class ModelAssetError(RuntimeError):
    """The manifest, the file or the hash is not what the configuration promised."""


@dataclass(frozen=True)
class ModelAsset:
    asset_id: str
    path: Path
    sha256: str
    bytes: int
    url: str | None
    licence: str | None

    @property
    def hash_prefix(self) -> str:
        return self.sha256[:12]


def assets_root() -> Path:
    override = os.environ.get(_ENV)
    if override:
        return Path(override).resolve()
    return repo_root() / "assets"


def manifest_path() -> Path:
    return assets_root() / "models" / MANIFEST_NAME


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_model_asset(asset_id: str, *, verify: bool = True) -> ModelAsset:
    """Look ``asset_id`` up in the manifest and (by default) verify the file's SHA-256."""
    mpath = manifest_path()
    if not mpath.exists():
        raise ModelAssetError(
            f"no model manifest at {mpath}; run scripts/fetch_hand_landmarker_model.py once "
            f"(docs/environment.md section 7)"
        )
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    entry = manifest.get("assets", {}).get(asset_id)
    if entry is None:
        raise ModelAssetError(f"model asset {asset_id!r} not in {mpath}")
    path = mpath.parent / entry["file"]
    if not path.exists():
        raise ModelAssetError(f"model file {path} listed in the manifest is missing")
    if verify:
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise ModelAssetError(
                f"model file {path.name} SHA-256 {digest[:16]}... differs from the manifest's "
                f"{entry['sha256'][:16]}...; refusing to load an unpinned model"
            )
    return ModelAsset(asset_id=asset_id, path=path, sha256=entry["sha256"], bytes=int(entry["bytes"]),
                      url=entry.get("url"), licence=entry.get("licence"))


__all__ = ["ModelAsset", "ModelAssetError", "assets_root", "manifest_path", "resolve_model_asset",
           "sha256_file"]
