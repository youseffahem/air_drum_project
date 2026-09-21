"""Phase 03, Task 03.1: download the MediaPipe Hand Landmarker task file ONCE and pin its hash.

docs/environment.md section 7 ("No network at runtime"): any model or asset is downloaded once by
a documented script, stored under ``assets/`` with a SHA-256 in a manifest, and loaded from disk.
This is that script for the hand-landmark estimator candidate (README section 14, phase-03 Task 03.1).

    python scripts/fetch_hand_landmarker_model.py            # download if missing, then verify
    python scripts/fetch_hand_landmarker_model.py --verify   # verify only (never touches the network)

Behaviour:

* The URL is the **versioned** Google model bucket path (``.../float16/1/...``), never ``latest``,
    so the file the manifest pins is the file every later run loads.
* On first download the SHA-256 is computed and written to ``assets/models/manifest.json`` together
  with the source URL, size, licence and the ``mediapipe`` version that consumed it.
* On every later call (and with ``--verify``) the file on disk is hashed and compared with the
  manifest; a mismatch is reported and the exit code is non-zero. Nothing silently re-downloads.
* ``spacedrums.hands`` loads the model from the manifest path and re-checks the hash at load time
  (``detector_id`` embeds the hash prefix), so a swapped file cannot go unnoticed in a run log.

The task file is a binary the repository may or may not track (owner decision, see the Task 03.1
evidence note); the manifest is always tracked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "models"
MANIFEST = ASSETS / "manifest.json"

MODEL = {
    "asset_id": "mediapipe-hand-landmarker-float16-v1",
    "file": "hand_landmarker.task",
    "url": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
    "licence": "Apache-2.0 (MediaPipe model card: Hand Landmarker; Google LLC)",
    "purpose": "Phase 03 Task 03.1 hand-landmark estimator candidate (21 keypoints + handedness).",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"schema": "assets-manifest/1", "assets": {}}


def verify(entry: dict) -> tuple[bool, str]:
    path = ASSETS / entry["file"]
    if not path.exists():
        return False, f"missing: {path}"
    digest = sha256_file(path)
    if digest != entry["sha256"]:
        return False, (f"SHA-256 mismatch for {path.name}: disk {digest[:16]}... "
                       f"manifest {entry['sha256'][:16]}...")
    return True, f"ok: {path.name} sha256:{digest} ({path.stat().st_size} bytes)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="verify the manifest against disk; no network")
    args = ap.parse_args(argv)

    manifest = load_manifest()
    entry = manifest["assets"].get(MODEL["asset_id"])
    path = ASSETS / MODEL["file"]

    if entry is None and args.verify:
        print(f"RESULT: FAIL no manifest entry for {MODEL['asset_id']} ({MANIFEST})")
        return 2

    if entry is None:
        ASSETS.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            print(f"downloading {MODEL['url']} -> {path}")
            with urllib.request.urlopen(MODEL["url"], timeout=120) as resp, path.open("wb") as out:  # noqa: S310
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
        else:
            print(f"file already present, pinning it without download: {path}")
        try:
            import mediapipe as mp

            mp_version = str(mp.__version__)
        except Exception:  # noqa: BLE001 - version is provenance only
            mp_version = "unknown"
        entry = {
            **MODEL,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "pinned_with_mediapipe": mp_version,
            "note": ("Downloaded once (docs/environment.md section 7). "
                     "spacedrums.hands re-checks this hash at load."),
        }
        manifest["assets"][MODEL["asset_id"]] = entry
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"manifest written: {MANIFEST}")

    ok, msg = verify(entry)
    print(msg)
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
