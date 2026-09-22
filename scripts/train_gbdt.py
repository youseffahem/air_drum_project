"""Train one or more Phase 08 feature folds without accessing held-out test data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spacedrums.models.gbdt.train import train_fold


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=9)
    args = parser.parse_args()
    folds = sorted(args.features_dir.glob("fold-*"))
    if not folds:
        parser.error("no fold-* feature directories found")
    for fold in folds:
        manifest = train_fold(fold, args.output / fold.name, seed=args.seed)
        print(
            json.dumps(
                {
                    "fold": fold.name,
                    "source_kind": manifest["evidence_kind"],
                    "selected": manifest["selected"],
                }
            )
        )


if __name__ == "__main__":
    main()
