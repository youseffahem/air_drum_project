# spacedrums.app

## Phase 14 calibration

Status: IMPLEMENTED development machinery; developer live calibration PENDING.
See [ADR-0037](../../../docs/decisions/ADR-0037-calibration.md), the user procedure
[`docs/user/calibration.md`](../../../docs/user/calibration.md) and the
[Phase 14 gate](../../../docs/gates/phase-14-gate.md).

```powershell
.venv/Scripts/python.exe -m spacedrums.app.calibrate --user-tag dev-jo            # live wizard (MVP-4)
.venv/Scripts/python.exe -m spacedrums.app.calibrate --synthetic --user-tag t --output <file>  # SYNTHETIC
.venv/Scripts/python.exe -m spacedrums.app.main --calibration configs/calibration/<file>.calib.yaml
```

`calibrate.py` drives the wizard with live frames, replayed frames (`--source replay`, a development
diagnostic that skips validation) or the SYNTHETIC actor, through an **Arm-A-only** pipeline (no rule
arm, no model). It uses the calibrated per-hand `L_prior` after step 3 and the fitted zones for the
test strikes. Partial progress is kept for `--resume`; `--check` reports re-calibration triggers.
`main.py` resolves configs with `calib.load_calibrated_config` (`--calibration` or `calibration_path`),
refuses a stale calibration (exit 2) and records `calibration_status/_hash/_id` in `session.json`. A
recorded session also keeps a copy of the calibration file. `arms.build_model_arm` verifies a model
against the calibration's template layout and feeds ZONE features from the calibrated zones.

## Phase 13 temporal arm

Status: IMPLEMENTED development integration; full gate PENDING.
See [ADR-0036](../../../docs/decisions/ADR-0036-live-model-integration.md) and the
[Phase 13 gate](../../../docs/gates/phase-13-gate.md).

Run from the repository root:

```powershell
# Baselines, with the other arm logged in shadow:
.venv/Scripts/python.exe -m spacedrums.app.main --arm A --shadow B
.venv/Scripts/python.exe -m spacedrums.app.main --arm B --shadow A
# Experimental C, pinned SYNTHETIC-trained development package; not a shipped model:
.venv/Scripts/python.exe -m spacedrums.app.main --config configs/live.arm-C.candidate.yaml --arm C-GRU --shadow A B --record
# Raw replay with original timestamps:
.venv/Scripts/python.exe -m spacedrums.app.main --config configs/live.arm-C.candidate.yaml --source replay --session-dir data/dev-captures/swing-L2-exp-5 --no-audio --record
```

Keys `a`/`b`/`c` select a running arm; `c` means the configured GRU or TCN.
The other running arms remain shadow-only. The overlay shows the actual active arm
and model failure. Fallback disables further model computation, chooses B (or A),
and records its reason. Fix the package/budget/rate issue and restart to restore C.
Already committed audio is never cancelled. Inference runs synchronously; windows
are bounded and independent per hand.

Record mode now includes KinematicFeatures and model trajectories. `session.json`
contains model id, requested hashes/runtime, switches and fallback events, while
every committed strike carries its actual arm/shadow flag. Use `parity_test.py` for
formal Phase 09 comparison; ordinary app replay uses its explicit replay delay.

The example's ignored Phase 10 model/statistics paths must exist locally. A missing
or mismatched package produces a logged fallback; it does not select another model.
The default prototype remains an A/B config. Live strokes and participant parity
are still required before the full Phase 13 gate can pass.

## Baseline application

**Status:** IMPLEMENTED (Phase 05, Task 05.5; ADR-0018). Composition root (layer L8): the playable prototype.

- `pipeline.DecisionPipeline` — per frame: tracking (both hands) → Phase 04 geometry on the observed trajectory (arm A) → rule-based extrapolation + the same geometry (arm B) → one commit policy per arm per hand → audio for the active arm → `TimingRecord`s. Consumes observations, so it runs on live perception, replay and labelled SYNTHETIC sequences alike.
- `main` — CLI: `--source live | replay | devcapture`, `--synthetic <scenario>`, keyboard `a`/`b` arm switch, `--record` (record mode), `--no-audio`, `--audio-output-latency-s` **only with** `--audio-latency-run-id` (otherwise the DAC estimate is withheld), `--replay-delta-proc-s` (provisional replay `t_now`).
- `audio_out.AudioOutput` — scheduler + sample bank + mixer + device with explicit `OutputLatency` provenance (PENDING on HW-01).
- `recorder.SessionRecorder` — frames (lossless PNG) + `frames.jsonl` + header-first record streams + `timing.jsonl` + `config.snapshot.yaml` + `session.json` (Phase 05 developer provenance; not the Phase 06 `SessionMetadata`).
- `session_summary` — counts, README §5.3 decomposition, informal B-vs-A comparison, SYNTHETIC-truth evaluation, non-VALID commit count (developer sanity-check machinery; Phase 09 owns the canonical harness).
- `synthetic` — deterministic SYNTHETIC observation sequences and scenarios (never evidence).

Tests: `tests/app/`. Scripts: `scripts/playability_session.py`, `scripts/induced_loss_test.py`, `scripts/timing_summary.py`, `scripts/shadow_compare.py`, `scripts/rule_baseline_sensitivity.py`, `scripts/render_session_frames.py`. Phase 13 adds arm C.
