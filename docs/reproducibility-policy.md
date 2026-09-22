# Reproducibility Policy

**Phase:** 00 — Task 00.5 · **Status:** PLANNED as policy; the experiment-log schema is IMPLEMENTED and its test passes (`scripts/env_smoke.py`).
**Consumers:** Phase 09 harness uses the shared `scripts/_runlog.py` experiment-log writer; Phases 10–19 use the same schema; Phase 21 cites it in the reproducibility appendix.
**Related:** [`../phases/README.md`](../phases/README.md) §4 (VALIDATED requires reproduction), §13; [`repo-layout.md`](repo-layout.md) §3; [`environment.md`](environment.md); REQ-308.

## 1. Principle

A number may appear in a document only if a reader can (a) find the run that produced it, (b) re-create the run's inputs (code, config, data, environment, hardware description, seed), and (c) know how closely a re-run is expected to match. Everything below serves those three needs.

## 2. Seeding

| Component | Rule |
|---|---|
| Global seed | One integer `seed` per run, recorded in `run.json`. Default candidate seeds for multi-seed experiments: a fixed list declared in the phase document (e.g. `[0, 1, 2]`) — *candidate*, not a result. |
| Python | `random.seed(seed)` |
| NumPy | `np.random.default_rng(seed)` passed explicitly to every consumer; the legacy global `np.random.seed` is **also** set for third-party code. |
| PyTorch | `torch.manual_seed(seed)`; `torch.use_deterministic_algorithms(True)` where supported; `torch.set_num_threads(n)` with `n` recorded. Data loaders: `shuffle` only with a `torch.Generator` seeded from `seed`; `num_workers=0` in evaluation runs; `worker_init_fn` seeds workers deterministically in training runs. |
| GBDT (LightGBM / XGBoost) | `seed`/`random_state` = `seed`; `deterministic=True` and `force_row_wise=True` (LightGBM) or equivalent; `num_threads` recorded. |
| Data ordering | Dataset item order is defined by the **manifest order** (sorted by participant id, session id, segment id), never by filesystem listing order. Splits are read from the versioned split file, never recomputed at run time. |
| Non-deterministic sources | Anything else (thread scheduling, OS timing) is declared in the run's `notes` and covered by the tolerance policy (§6). |

## 3. Configuration snapshot

- Every run resolves its configuration (defaults + file + CLI overrides) into **one** in-memory object, validates it against the config schema (Phase 01), and writes it to `config.resolved.yaml` in the run directory **before** any computation.
- `config_hash = "sha256:" + SHA256(canonical_json(resolved_config))`, where `canonical_json` = UTF-8, keys sorted recursively, no insignificant whitespace, floats serialised with `repr`, `NaN`/`Inf` forbidden.
- Config files are versioned by name (`<component>.<variant>.v<N>.yaml`, `repo-layout.md` §3.1) and never edited in place after a run cites them.

## 4. Code, data, environment, hardware provenance

| Field | Rule |
|---|---|
| `git_sha` | Full 40-hex commit hash of `HEAD` at run start. |
| `git_dirty` | `true` if `git status --porcelain` is non-empty (ignoring `data/`, `experiments/`, `.venv/`). Dirty runs are allowed during development but **cannot be cited as MEASURED in a gate record or thesis**, and cannot form a VALIDATED pair. |
| `dataset_version`, `dataset_hash` | Version string and SHA-256 of that version's `manifest.json` (`repo-layout.md` §3.4). Runs without a dataset use `ds-none-v0.0` and must justify it in `description`. |
| `split` | The participant-level split actually used, copied into the record (ids only). Any ML result cited must have `train ∩ test = ∅` at participant level (integrity checklist item I-8). |
| `environment.python`, `environment.lock_hash` | Interpreter version and SHA-256 of `requirements.lock`. Optional: `libraries{}` and `threads{}`. |
| `hardware_id`, `hardware{}` | Id of a descriptor in `hardware-inventory.md` **and** an inline snapshot (CPU model, physical/logical cores, RAM, OS build, camera model, audio device) so the record survives inventory edits. |
| `started_at`, `finished_at` | ISO-8601 with timezone offset. |

Hashing scheme: SHA-256 everywhere. Datasets: a manifest listing every file's relative path, byte size, SHA-256; the manifest is hashed as a file. Models: listed in `models/manifest.json` with SHA-256; a loaded model's hash is verified at load time (Phase 13).

## 5. Experiment-log schema

Defined in [`../schemas/experiment-log.schema.json`](../schemas/experiment-log.schema.json) (JSON Schema 2020-12, `schema_version: "1.0"`). Required fields:

```
schema_version, run_id, phase, task, status, config_hash, config_path,
dataset_version, dataset_hash, git_sha, git_dirty, hardware_id, environment{python, lock_hash},
seed, started_at, finished_at, metrics{}, artefacts[]
```

Optional: `description`, `arm`, `split{}`, `hardware{}`, `deterministic`, `parent_run_id`, `notes`. `additionalProperties` is `false` at the top level so typos cannot silently create new fields.

Rules:
- One `run.json` per run directory (`experiments/<run_id>/`). The harness writes it with `status: RUNNING` at start and rewrites it once at the end.
- `metrics` keys use the canonical names from README §10 (e.g. `plt_median_s`, `fp_per_min`, `te_pred_mae_s`, `ade_norm`, `fde_px`, `inference_p95_ms`) — the exact key list is frozen by Phase 09 and appended to this document then.
- Every artefact (model, figure, table, predictions file) is listed with its SHA-256; figures in the thesis cite the `run_id` that produced them.
- Schema test (this phase): the valid example is accepted; a record missing `dataset_version` is rejected. Verified: `scripts/env_smoke.py` → `PASS` on 2026-09-20.

## 6. "Same result" tolerance policy for VALIDATED

VALIDATED (README §4) requires a second run that reproduces a MEASURED result. The two runs form a **reproduction pair** (`parent_run_id` links them). Both must have `git_dirty: false`, identical `config_hash`, `dataset_hash`, `lock_hash`, and `seed`.

| Code path | Tolerance |
|---|---|
| Deterministic (geometry, event matching, metric computation, feature extraction, replay of recorded tracks, rule-based baselines A/B) | **Exact**: bit-identical metric values and identical committed-strike lists. Any difference is a bug. |
| GBDT training/inference with fixed seed and threads | Exact on the same hardware descriptor; documented tolerance if the hardware differs (record both `hardware_id`s). |
| PyTorch training (CPU) with deterministic algorithms | Metrics must agree within a **pre-declared** tolerance stated in the phase document *before* the runs (candidate: relative 1 % on ADE/FDE and absolute 1 ms on timing metrics — *candidate values*, to be fixed by Phase 09/10). Committed-strike lists may differ; the difference count is reported. |
| Anything involving wall-clock timing (inference latency, end-to-end latency, FPS) | Not reproduced bit-for-bit. VALIDATED requires a repeat measurement on the same `hardware_id` with the same thread settings, reporting both distributions (p50/p95/p99) and the phase-declared acceptance band. |
| Live captures (camera in the loop) | Never VALIDATED by replay; only by an independent repeat session under the same documented conditions, reported as two MEASURED values. |

If a pair fails its tolerance, the result stays MEASURED and the discrepancy is recorded in the gate record; it may not be promoted.

## 7. Experiment tracking tool

`Pending Architecture Decision` (Phase 00 → resolved here as the **default**): file-based manifests as specified above are the system of record. A lightweight tracker (e.g. a local SQLite index or MLflow file store) may be added by Phase 09 for browsing **only if** it is derived from the `run.json` files and never becomes a second source of truth. Recorded in ADR form only if adopted.

## 8. Reporting rules that follow from this policy

- Every number in a document names its `run_id` (or a gate record that lists the runs).
- Every number is labelled Target / Measured / Historical / Pending (README §4). A superseded measurement becomes **Historical** and keeps its `run_id`.
- No metric is quoted from a `status != COMPLETED` run.
- Thread counts and hardware ids accompany every latency/FPS figure.
