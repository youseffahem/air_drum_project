"""Train/export one Phase 11 multi-task model on one Phase 08 fold; never reads held-out samples."""

import argparse
import json
from pathlib import Path

from _p10 import hardware, provenance, source_hashes, write_json
from _p11 import train_and_export_mt
from _runlog import RunLog

from spacedrums.config import load_config
from spacedrums.models.temporal.config import MultiTaskConfig
from spacedrums.models.temporal.mt_train import MultiTaskLossConfig
from spacedrums.models.temporal.train import TrainConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fold-dir", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, required=True, help="JSON with mt_config/training/loss/aux_horizon_s"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding="utf-8"))
    config = MultiTaskConfig.from_dict(settings["mt_config"])
    training, loss = TrainConfig(**settings["training"]), MultiTaskLossConfig(**settings.get("loss", {}))
    with RunLog(
        phase="11",
        task="11.1",
        slug="mt-training",
        seed=training.seed,
        config=load_config("configs/prototype.candidate.yaml"),
        experiments_dir=args.output,
        description="Multi-task fold training/export; evidence kind in the model manifest",
    ) as run:
        context = {**provenance(), "hardware": hardware()}
        context["codex_model"] = "NOT CODEX: Claude Opus 5.5 (claude-opus-5-5) via Claude Code"
        context["codex_reasoning_effort"] = "UNAVAILABLE to the agent; not asserted"
        write_json(run.dir / "settings.json", settings)
        write_json(run.dir / "source-hashes.json", source_hashes())
        _, manifest, _, metrics = train_and_export_mt(
            args.fold_dir,
            run.dir / "model",
            config,
            training,
            loss,
            context=context,
            aux_horizon_s=settings.get("aux_horizon_s"),
        )
        for path in (run.dir / "model").iterdir():
            run.add_artefact(path, "other")
        run.add_artefact(run.dir / "settings.json", "other")
        run.add_artefact(run.dir / "source-hashes.json", "other")
        run.finish(
            {"validation": metrics, "source_kind": manifest["source_kind"]},
            notes="Selection, held-out evaluation and reviewer validation remain separate.",
        )


if __name__ == "__main__":
    main()
