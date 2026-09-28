# Phase 19 preparation — file inventory

Current changes only; no commit, tag or push. All experiment output is SYNTHETIC/DEV under ignored `experiments/phase-19/`.

| File | Purpose |
|---|---|
| `.importlinter` | Architecture enforcement |
| `configs/ablations/synthetic-dev.yaml` | Plan/reference contracts or per-arm configuration |
| `configs/live.arm-C.candidate.yaml` | Plan/reference contracts or per-arm configuration |
| `configs/schema/README.md` | Plan/reference contracts or per-arm configuration |
| `configs/schema/config.schema.json` | Plan/reference contracts or per-arm configuration |
| `docs/architecture/architecture.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/architecture/contracts.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/decisions/ADR-0036-live-model-integration.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/decisions/ADR-0043-ablation-preparation.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/experiments/phase-19-prereg.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/gates/phase-19-gate.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/reports/phase-19-ablations.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/reports/phase-19-files.md` | Draft protocol, status, evidence or architecture documentation |
| `docs/testing/test-matrix.md` | Draft protocol, status, evidence or architecture documentation |
| `phases/phase-19-ablation-study.md` | Draft protocol, status, evidence or architecture documentation |
| `schemas/README.md` | Plan/reference contracts or per-arm configuration |
| `schemas/ablation-plan.schema.json` | Plan/reference contracts or per-arm configuration |
| `schemas/ablation-reference.schema.json` | Plan/reference contracts or per-arm configuration |
| `schemas/confirmatory-lock.schema.json` | Plan/reference contracts or per-arm configuration |
| `schemas/examples/ablation-plan.valid.example.json` | Plan/reference contracts or per-arm configuration |
| `scripts/_p13.py` | Orchestration, verification or existing harness integration |
| `scripts/_p18.py` | Orchestration, verification or existing harness integration |
| `scripts/_p19.py` | Orchestration, verification or existing harness integration |
| `scripts/build_test_matrix.py` | Orchestration, verification or existing harness integration |
| `scripts/confirmatory_lock.py` | Orchestration, verification or existing harness integration |
| `scripts/run_ablations.py` | Orchestration, verification or existing harness integration |
| `scripts/run_offline_confirmatory.py` | Verify frozen config pins alongside Python package sources |
| `scripts/validate_contracts.py` | Orchestration, verification or existing harness integration |
| `scripts/verify_phase19.py` | Orchestration, verification or existing harness integration |
| `src/spacedrums/ablation/README.md` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/__init__.py` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/config.py` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/guards.py` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/report.py` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/retrack.py` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/statistics.py` | Offline ablation preparation machinery |
| `src/spacedrums/ablation/transforms.py` | Offline ablation preparation machinery |
| `src/spacedrums/app/invariants.py` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/app/pipeline.py` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/calib/store.py` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/commit/invariants.py` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/config/README.md` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/config/loader.py` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/live_eval/arm_settings.py` | ADR-0036 runtime, audit, config or lock consistency |
| `src/spacedrums/live_eval/prereg.py` | ADR-0036 runtime, audit, config or lock consistency |
| `tests/ablation/conftest.py` | Automated engineering/guard coverage |
| `tests/ablation/test_ablation.py` | Automated engineering/guard coverage |
| `tests/ablation/test_retrack.py` | Automated engineering/guard coverage |
| `tests/app/test_per_arm_settings.py` | Automated engineering/guard coverage |
| `tests/architecture/test_import_layers.py` | Automated engineering/guard coverage |
| `tests/calib/test_per_arm_calibration.py` | Automated engineering/guard coverage |
| `tests/contracts/test_config_schema.py` | Unknown-version rejection updated for schema 1.9 |
| `tests/invariants/test_per_arm_audit.py` | Automated engineering/guard coverage |
| `tests/parity/test_per_arm_model.py` | Automated engineering/guard coverage |
| `tests/scripts/test_phase18_scripts.py` | Frozen config/source inventory regression and tamper tests |

55 modified/new files. No tracked Phase 18 preregistration or experimental-result file changed.
