"""Fetch the versioned standing-reference model, pin its digest beside the hand model."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ASSET = "mediapipe-pose-landmarker-full-float16-v1"
URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/1/pose_landmarker_full.task"
)


def main():
    root = Path(__file__).resolve().parents[1] / "assets/models"
    manifest = root / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    path = root / "pose_landmarker_full.task"
    blob = path.read_bytes() if path.exists() else urllib.request.urlopen(URL, timeout=60).read()
    digest = hashlib.sha256(blob).hexdigest()
    old = data["assets"].get(ASSET)
    if old and old["sha256"] != digest:
        raise ValueError("pose model hash differs from pinned manifest")
    if not path.exists():
        path.write_bytes(blob)
    data["assets"][ASSET] = {
        "asset_id": ASSET,
        "file": path.name,
        "url": URL,
        "sha256": digest,
        "bytes": len(blob),
        "licence": "Apache-2.0 (MediaPipe model card, Google LLC)",
        "purpose": "Standing reference only; full variant candidate, not a strike model.",
    }
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{ASSET}: {len(blob)} bytes sha256={digest}")


if __name__ == "__main__":
    main()
