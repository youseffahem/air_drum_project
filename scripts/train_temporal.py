"""Train/export one Phase 08 validation fold; never reads held-out samples."""

import argparse
import json
from pathlib import Path

from _p10 import hardware, provenance, source_hashes, train_and_export, write_json
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.models.temporal import TemporalConfig
from spacedrums.models.temporal.train import TrainConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True, help="JSON with model/training/aux_horizon_s")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding="utf-8"))
    config = TemporalConfig(**settings["model"])
    training = TrainConfig(**settings["training"])
    with RunLog(
        phase="10",
        task="10.5",
        slug="temporal-training",
        seed=training.seed,
        config=load_config("configs/prototype.candidate.yaml"),
        experiments_dir=args.output,
        description="Temporal fold training/export; evidence kind in model manifest",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        write_json(run.dir / "settings.json", settings)
        write_json(run.dir / "source-hashes.json", source_hashes())
        _, manifest, _, metrics = train_and_export(
            args.fold_dir,
            run.dir / "model",
            config,
            training,
            context=context,
            aux_horizon_s=settings.get("aux_horizon_s"),
        )
        for path in (run.dir / "model").iterdir():
            run.add_artefact(path, "other")
        run.add_artefact(run.dir / "settings.json", "other")
        run.add_artefact(run.dir / "source-hashes.json", "other")
        run.finish(
            {"validation": metrics, "source_kind": manifest["source_kind"]},
            notes="Model selection, held-out evaluation and reviewer validation remain separate.",
        )


if __name__ == "__main__":
    main()
