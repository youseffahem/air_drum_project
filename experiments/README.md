# experiments/

**Git-ignored** except this file. One directory per run: `<YYYYMMDD>-<HHMM>-<slug>/` containing `run.json`
(valid against `schemas/experiment-log.schema.json`), `config.resolved.yaml`, `stdout.log`, and listed artefacts.
Run directories are immutable once `status: COMPLETED`. See docs/reproducibility-policy.md.
