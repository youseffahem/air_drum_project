# tests/

`tests/scripts/test_phase05_scripts.py` (Phase 05); `tests/data/`, `tests/scripts/test_phase06_scripts.py` (Phase 06); `tests/labels/`, `tests/contracts/test_label_schemas.py`, `tests/scripts/test_phase07_scripts.py` (Phase 07). Everything else PLANNED.

Layout mirrors `src/spacedrums/<subpackage>/` as `tests/<subpackage>/test_*.py`; cross-cutting suites under `tests/architecture/` (layer rules), `tests/scripts/` (measurement scripts in synthetic mode), later `tests/system/`.

Run (repository root): `.venv\Scripts\python.exe -m pytest` (configuration in `pyproject.toml`). Hardware tests are opt-in: `set SPACEDRUMS_HW_TESTS=1` runs `tests/capture/test_hardware_capture.py` against the webcam.

Test ids cited by gate records (`docs/repo-layout.md` section 3.5): `TEST-SCHEMA-1` (contracts), `TEST-TIMING-1`, `TEST-CONFIG-1`, `TEST-CAPTURE-1…5`, `TEST-UI-1`, `TEST-ARCH-1`, `TEST-SCRIPTS-1`, `TEST-HANDS-1…4` (coordinate boundary; wrapper with injected backend; real model — skipped with a reason when `assets/models/hand_landmarker.task` is absent; identity assignment on synthetic sequences; grip reference), `TEST-STICK-1…2` (search region / segmentation / axis on synthetic images; the three tip estimators), `TEST-CONFORM-1` (TipEstimator) and `TEST-CONFORM-2` (Tracker), `TEST-TRACK-1…3` (filters on synthetic trajectories, every state-machine transition, tracker + occlusion trace), `TEST-CAUSAL-1` and `TEST-CAUSAL-2` for the tracker (`tests/tracking/test_causal.py`, synthetic + recorded dev capture when present); the live-source case of `TEST-CONFORM-7` is in `tests/capture/test_source.py`. Causality/parity suites: `docs/architecture/causality-tests.md`, implemented by the phases named there.

Phase 05 ids: `TEST-PRED-1…3` (analytic crossing, gate monotonicity, failure cases), `TEST-CONFORM-3` (rule-based `Anticipator`), `TEST-CONFORM-5` (commit policy property test), `TEST-COMMIT-1…2` (every transition and gate), `TEST-CAUSAL-1/2` for the anticipator (`tests/prediction/test_causal_anticipator.py`) and the commit policy (`tests/commit/test_causal_commit.py`), `TEST-APP-1…10` (synthetic hit types, shadow safety, arm switch, deterministic replay, induced loss, failure cases, record mode + replay reproduction, session summary), `TEST-TIMING-2` (TimingRecord, collector, streams, decomposition), `TEST-CONFORM-7` replay case, `TEST-SCRIPTS-2` (Phase 05 scripts in `--synthetic` mode). Helpers for these suites live in uniquely named modules (`app_helpers.py`, `commit_helpers.py`, `synthetic_histories.py`) because `from conftest import …` is order-fragile across directories.

Phase 06 ids: `TEST-DATA-1…6` (`tests/data/`: protocol vocabulary + seeded zone order + marker integrity; `SessionMetadata` kinds, consent gating, structural promotion refusal, `has_phys_gt`, re-takes; guided-recorder hooks; audio capture / onsets / sync on SYNTHETIC signals; session verification on a SYNTHETIC session with every corruption case and the policy thresholds; raw manifests with kind gating, tamper detection, withdrawal), `TEST-SCRIPTS-3` (`tests/scripts/test_phase06_scripts.py`: the Phase 06 scripts in SYNTHETIC / DEV CAPTURE modes; `--live` refuses without `--kind`); dataset schemas in `tests/contracts` via `DATASET_SCHEMAS`. Helper: `tests/data/data_helpers.py` (records a short SYNTHETIC protocol session through the real record mode). No test records a person.

Phase 07 ids: `TEST-LABEL-1…10` (`tests/labels/`: every labelling rule on constructed evidence plus the surface-distance helpers; the non-causal reference smoother — correctness on closed-form signals, the property that a sample depends on *later* measurements, gap policy, parameter guards, determinism; the linear and quadratic sub-frame estimators and the pre-declared comparison rule; the generator end to end on a SYNTHETIC session — determinism, provenance, causal/reference separation, labels within one frame of the analytic crossing, one positive per episode, kind gating; the validator with a corruption per check; the QC round-trip, correction history, second-pass disagreement and Cohen's kappa; acoustic pairing and the `has_phys_gt` per-strike invariant; statistics that refuse to mix evidence classes, the labelled-dataset manifest and the dataset card; participant-level splits and the leakage checks; and the structural leakage scan that fails if any causal package — or `features/` / `models/`, which pass vacuously until Phase 08 creates them — imports the label machinery or reads `tracks_reference`). Label schemas in `tests/contracts/test_label_schemas.py` via `LABEL_SCHEMAS`; `TEST-SCRIPTS-4` (`tests/scripts/test_phase07_scripts.py`: every Phase 07 script and the review tool in their self-test modes, including the refusals). Helper: `tests/labels/label_helpers.py` (records **and labels** a short SYNTHETIC session through the real generator; `tests/data` is on `pythonpath` so it can reuse `data_helpers.make_session`). **No test records a person, and no test produces participant labels: every session is `session_kind = SYNTHETIC` and can only carry a `ds-v0.0-selftest*` dataset version.**

Phase 08: `tests/features/` (TEST-FEATURE-1 analytic values/masks; TEST-CAUSAL-1/2;
TEST-FEATURE-2 train-only scaling; TEST-FEATURE-3 windows/targets; TEST-FEATURE-4
serialized loaders, reference exclusion and parity). `tests/scripts/test_phase08_scripts.py`
executes CLIs/config checks. The seeded property test is SYNTHETIC, as are all unit fixtures.
Participant parity remains pending. `scripts/verify_phase08.py` captures focused/full regression,
contracts, lint/import checks, environment/assets, replay/export and CPU timings. Existing
contract tests import `conftest` helpers directly; the combined focused command places
`tests/contracts` after directories with their own conftest to avoid initial-load shadowing.

Phase 10: `tests/temporal/` covers GRU/TCN TEST-CAUSAL-1/2, masked losses,
fixed-grid target interpolation, bounded GRU state, per-hand reset, streaming
feature parity, train/val/test isolation, deterministic training, both optional
head settings, TorchScript parity/tamper checks, geometry-only replay and neutral
selection/held-out refusal. Fixtures are explicitly SYNTHETIC; none is participant
evidence. `scripts/recorded_temporal_parity.py` separately verifies a DEV capture.

Phase 11: `tests/temporal/test_mt_*.py` (helpers in `mt_helpers.py`) cover head shapes and
TorchScript parity, masked multi-task losses (a sample without an impact feeds only the
trajectory and strike-negative losses), TTI parameterisations, weighting schemes,
TEST-CAUSAL-1/2 on every head, bit-identical trajectory-only vs Phase 10 training,
determinism/export/tamper per weighting, read-only conflict sampling, train-only intensity
scaling, consistency flags and gates, config 1.5 and TrajectoryPrediction 1.1 migration, and
the invariant that no CommittedStrike exists without a geometry candidate outside the flagged
diagnostic mode (which the application refuses). Fixtures are SYNTHETIC.

Phase 12: `tests/temporal/test_ext_*.py` (helpers in `ext_helpers.py`) and
`tests/geometry/test_geometry_probabilistic.py` cover TEST-CAUSAL-1/2 on every extension encoder,
head and decoder (attention masks every future position; the E5 base reads the current frame
only), increment/polynomial/mixture heads and the relaxed winner-takes-all loss, the detached-mean
Gaussian NLL, bounded-acceleration projection with a train-only bound, uncertainty layout round
trips, bit-identical training against Phase 10 when no extension is enabled, determinism, export
parity and tamper refusal per extension, two-rate targets as dense-grid columns, the E5 base equal
to Baseline B's CV extrapolation, known crossing probabilities (including 1 − Φ(d/σ)), a gate that
only relabels geometry candidates, the C-TT replay arm, script refusals, the declared variant
registry and the mechanical go/no-go rule. Fixtures are SYNTHETIC.
