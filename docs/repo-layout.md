# Repository Layout & Naming Conventions

**Phase:** 00 — Task 00.4 · **Status:** IMPLEMENTED (skeleton directories with README stubs exist; no package code)
**Depends on:** Task 00.3 ([`environment.md`](environment.md)). Phase 01 may amend this layout by ADR (Phase 00 risk: "over-specifying before contracts exist" — layout is deliberately minimal).

## 1. Top-level layout

```
air_drum_project/
├── project-discovery.md          # primary requirements source (read-only after Phase 00)
├── phases/                       # roadmap: README.md + phase-00 … phase-23
├── docs/                         # all human-readable specifications and records
│   ├── requirements/             # rtm.md, out-of-scope.md
│   ├── decisions/                # ADR-NNNN-<slug>.md + README.md (index)
│   ├── ethics/                   # information-sheet.md, consent-form.md, ethics-approval-note.md
│   ├── gates/                    # gate-procedure.md, gate-record-template.md, phase-XX-gate.md
│   ├── environment.md
│   ├── repo-layout.md            # this file
│   ├── reproducibility-policy.md
│   ├── integrity-checklist.md
│   └── hardware-inventory.md
├── schemas/                      # JSON Schemas (experiment log, later: dataset manifest, config)
│   └── examples/                 # example records used by schema tests
├── configs/                      # versioned YAML configs (Phase 01 defines the schema)
│   └── schema/                   # config schema placeholder (pydantic models / JSON Schema)
├── src/spacedrums/               # the Python package (empty stubs until Phase 02)
│   ├── capture/  hands/  stick/  tracking/  features/  geometry/
│   ├── prediction/  commit/  audio/  ui/  eval/  data/  calib/
├── tests/                        # pytest suites, mirrored by subpackage from Phase 02 on
├── scripts/                      # one-off tools; Phase 00: env_smoke.py only
├── experiments/                  # run directories (git-ignored except README.md)
├── data/                         # datasets & recordings (git-ignored except README.md; manifest-tracked)
├── requirements.in / requirements.lock
├── .gitignore
└── .venv/                        # local virtual environment (git-ignored)
```

Later phases add, without changing the above: `models/` (exported model artefacts + manifest, Phase 10/13), `assets/` (drum samples, MediaPipe task files, licences — Phase 04/03), `thesis/` (Phase 21), `release/` (Phase 23). Each addition is announced in the phase document's *Artifacts Produced* section.

## 2. Package → pipeline stage mapping

| Subpackage | Pipeline stage(s) (README §1) | Owning phase |
|---|---|---|
| `capture/` | Webcam, fixed playing ROI, timestamp mapping to `t_mono` | 02 |
| `hands/` | Hand detection / landmarks, handedness | 03 |
| `stick/` | Stick detection/segmentation, axis estimation, `TipEstimator` (`GEOM`, `AXIS_REFINED`, `MARKER`) | 03 |
| `tracking/` | Causal per-hand temporal tracker, README §8 state machine | 03 |
| `features/` | Causal kinematic feature schema (offline = online code path) | 08 (13 parity) |
| `geometry/` | Zone registry, impact surfaces, crossing test, sub-frame interpolation, trajectory–zone intersection | 04 |
| `prediction/` | `Anticipator` implementations: rule-based (B), GBDT (C-GBDT), temporal models (C-GRU/TCN/MT/TT) | 05, 09, 10–12 |
| `commit/` | Commit state machine, refractory, duplicate suppression, safety checks | 05 |
| `audio/` | Drum engine, sample bank, time-targeted scheduling, output-latency measurement | 04 |
| `ui/` | Stand-here guide, zone drawing, debug overlay/dashboard | 02, 15 |
| `eval/` | Causal replay simulator, event matching, canonical metrics, experiment-log writer | 09 |
| `data/` | Recording tool, session metadata, dataset manifests, labelling/QC tools, splits | 06, 07 |
| `calib/` | Calibration wizard and calibration file I/O | 14 |

The **canonical timing/event/metric definitions live in `phases/README.md` §5–§10** and are implemented once (`geometry/`, `eval/`); no subpackage redefines them.

## 3. Naming conventions

### 3.1 Config files — `configs/<component>.<variant>.v<N>.yaml`

- `<component>`: subpackage or concern name (`capture`, `zones`, `commit`, `model`, `harness`, `calib`, …).
- `<variant>`: short lowercase slug (`default`, `mvp4`, `v1-7zones`, `laptopcam`, `gru-h150ms`).
- `v<N>`: integer version, bumped on **any** change to values or keys. Old versions are never edited; they stay for reproducibility.
- Examples: `configs/zones.mvp4.v1.yaml`, `configs/capture.laptopcam.v2.yaml`, `configs/commit.default.v1.yaml`.
- Every config file carries a `meta:` block: `schema_version`, `created`, `phase`, `description`, `supersedes` (previous file or `null`).
- A run stores its **fully resolved** config (all defaults expanded, all includes merged) as `config.resolved.yaml` in the run directory, and its canonical SHA-256 as `config_hash` (see `reproducibility-policy.md` §3).

### 3.2 Model artefacts — `<family>-<task>-<dataset_version>-<seed>-<hash8>`

- `<family>`: `gbdt`, `gru`, `tcn`, `mt`, `tt` (README §9 arm codes, lowercase, without the `C-` prefix).
- `<task>`: `traj` (future trajectory), `mt` (multi-task), `strike` (GBDT window classifier/regressor), …
- `<dataset_version>`: e.g. `ds-v1.0`.
- `<seed>`: integer global seed.
- `<hash8>`: first 8 hex chars of the `config_hash` of the training run.
- Example: `gru-traj-ds-v1.0-17-3fa9c2e1.pt` and its export `gru-traj-ds-v1.0-17-3fa9c2e1.onnx`, both listed in `models/manifest.json` with full SHA-256.

### 3.3 Experiment runs — `experiments/<YYYYMMDD>-<HHMM>-<slug>/`

- Local time of run start; `<slug>` lowercase, hyphen-separated, ≤ 40 chars, states the purpose (`baselineA-fold3`, `gru-h150-sweepW`).
- The directory contains at least: `run.json` (validates against `schemas/experiment-log.schema.json`), `config.resolved.yaml`, `stdout.log`, and any artefacts listed in `run.json`.
- Run directories are **immutable** after `status: COMPLETED`. Corrections are new runs with `parent_run_id` set.

### 3.4 Dataset versions — `ds-v<major>.<minor>` (raw: `ds-raw-v<major>.<minor>`)

- `major` bumps when participants are added/removed or labelling rules change (splits are invalidated).
- `minor` bumps for metadata or QC corrections that do not change splits.
- Each version has a manifest `data/<version>/manifest.json` listing every file with SHA-256; the manifest's own SHA-256 is the `dataset_hash` of the experiment log.
- Raw recordings and labels are **never** committed to git; only manifests and dataset cards are (Phase 06/07).

### 3.5 Other identifiers

| Thing | Pattern | Example |
|---|---|---|
| Requirement | `REQ-NNN` / `REQ-NNNa` | `REQ-036`, `REQ-050b` |
| Decision record | `ADR-NNNN-<slug>.md` | `ADR-0003-mvp-zone-set.md` |
| Gate record | `docs/gates/phase-XX-gate.md` | `phase-00-gate.md` |
| Hardware descriptor | `HW-NN` | `HW-01` |
| Participant (pseudonym) | `P<NN>` | `P07` |
| Session | `P<NN>-S<N>` | `P07-S2` |
| Test id (Phase 01+) | `TEST-<AREA>-<N>` | `TEST-PARITY-1`, `TEST-CAUSAL-3` |
| Out-of-scope contact tag | `OOS-REF:REQ-2xx` | `# OOS-REF:REQ-207 kick zone slot reserved` |
| Python modules / functions | `snake_case`; classes `PascalCase`; constants `UPPER_SNAKE` | — |
| Timestamps in code | `t_<name>` in seconds on `t_mono` as `float`; never milliseconds in variables (ms only in reports, labelled) | `t_capture`, `t_commit` |

### 3.6 Git conventions (once the first commit exists)

- Default branch `main`; feature branches `phase-XX/<slug>`.
- Commit messages: imperative subject ≤ 72 chars, optionally prefixed `[PXX]`.
- Tags at each passed gate: `gate-XX-pass` (used by later phases to cite a code state).

## 4. What is *not* in the layout yet

- No `pyproject.toml` / package metadata: created in Phase 01 together with the first module contracts (keeping Phase 00 free of code).
- No `models/`, `assets/`, `thesis/`, `release/` directories: created by the phases that own them.
- No `tests/` content: the first tests arrive with Phase 01's contract tests.
