"""Fetch or verify the pinned public-domain TR-505 runtime sample bank."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets/samples/recorded-manifest.json"
BASE_URL = "https://oramics.github.io/sampled/DM/TR-505/samples"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Do not download missing files")
    args = parser.parse_args()
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures = []
    for entry in doc["samples"]:
        path = ROOT / "assets/samples" / entry["file"]
        expected = entry["sha256"].removeprefix("sha256:")
        if not path.exists() and not args.verify:
            path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(f"{BASE_URL}/{path.name}", path)  # noqa: S310
        actual = digest(path) if path.exists() else None
        ok = actual == expected
        print(f"{'OK' if ok else 'FAIL'} {entry['sample_id']} {actual or 'missing'}")
        if not ok:
            failures.append(entry["sample_id"])
    if failures:
        raise SystemExit(f"sample verification failed: {', '.join(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
