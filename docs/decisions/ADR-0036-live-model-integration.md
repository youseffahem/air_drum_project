# ADR-0036 — Verified live temporal arm and sticky fallback

Status: IMPLEMENTED development machinery; shipment and live timing PENDING.
Date: 2026-09-26. Phase: 13. Related: ADR-0026, ADR-0027, ADR-0030.

## Context

No participant model has been selected by the Phase 10/11 ship ADRs. Phase 12 adopted
no extension. The Phase 13 instruction permits independent executable work while
participant evidence and owner decisions remain pending. The example therefore
pins an existing **SYNTHETIC-trained development GRU**, without selecting it for shipment.
The baseline prototype config remains the normal A/B entry point.

## Decisions

- Support Phase 10 windowed TorchScript GRU/TCN packages. The app constructs the
  runtime and injects the adapter, stream and statistics into `ModelArm`. Prediction
  retains its no-geometry import boundary. No network service is used.
- Pin both manifest and export SHA-256 in config. Verify feature id/fingerprint,
  N/K/F, training step, normalization hash and fold/dataset/split provenance before
  loading. Reuse the Phase 10 loader's hashed model-configuration checks.
- Use windowed recomputation with shared weights and separate bounded histories
  for each hand. Phase 11's isolated development timings favored this over the
  bounded GRU cache; this is an implementation choice, not a Phase 16 optimization
  claim. Tracking resets clear that hand's stream and adapter state. INVALID/STALE
  clears that hand's history/window; no hidden state carries across a loss.
- Preserve delivered timestamps and actual dt. Requested capture rate must agree
  with training `dt_step`; a median native-interval guard also detects sustained
  mismatch at runtime. The guard divides by frame-id gaps, preserving dropped-frame
  accounting. Its 15-interval window and 25% tolerance are candidates, not validated
  thresholds. No interpolation, resampling, worker thread or future input is added.
- Route predictions through existing geometry and apply the Phase 10 inward-speed
  intensity calculation. Commit policy, geometry and the Phase 09 harness remain
  unchanged. No auxiliary direct-head strike path is enabled.
- Keep the established record labels `C-GRU` and `C-TCN`. Keyboard `c` selects the
  configured model; `a`/`b` select running baselines. Shadow commits are recorded
  but never scheduled. Switching resets commit confirmation state and suppresses
  commits on the transition frame; existing refractory timers persist.
- Monitor p95 of the **sum of both hands' adapter durations per frame**, and total
  perception-through-audio-scheduling processing, over a bounded window. Check
  inference before commit, total time after the completed frame. A total-budget
  failure therefore affects subsequent decisions; committed audio is never cancelled.
- On failure, disable model execution for the remainder of the session. If C was
  sounding, choose configured B, or A when B is unavailable. A failing shadow C
  leaves the active baseline unchanged. Record the reason and display the disabled
  state in the overlay. Automatic recovery is disabled; restart after fixing the
  fault. `cooldown_s` remains a reserved config field with no effect in this mode.

## Configuration and metadata

Schema 1.6 extends the existing `anticipator.model.{path,hash,...}` and fallback
blocks, retaining seconds and `window_frames` rather than introducing duplicate
flat `model_path`/`model_hash` or millisecond aliases. Older rule configs remain valid.
`rule` may remain populated with `type: model` so B can run in shadow/fallback.
The same configured K/step applies to B; it is recorded in the resolved config.

Developer `session.json` records the final active arm, all switches, fallback
events, verified model id and requested package/runtime settings. Every commit
retains its actual arm and shadow flag. Phase 06's metadata schema accepts the
optional model id and detailed fallback fields; its recording driver copies them
from the application summary. This does not create participant evidence.

## Parity and timing policy

`TEST-PARITY-1` starts with raw lossless recorded images and original timestamps.
The live perception/tracker feeds the production decision pipeline. A fresh
Phase 09 harness receives those delivered causal tracks, independently assembled
features and the same normalized model. This tests the feature-to-commit transfer;
the harness itself does not implement a second perception stack.

All feature masks and record fields are compared. Feature tolerance is 1e-10
absolute/relative; prediction/event numeric floats use the export tolerances 1e-6/1e-5.
Timestamp fields use absolute tolerance only, so large capture epochs cannot hide drift.
Candidate allocation ids differ because live geometry also allocates A/B candidates;
their commit links are checked separately. Inference/candidate wall-clock stamps
are excluded. Commit times use the **same per-frame capture-to-decision delay**,
including recorded capture delivery and measured perception/decision work.

Raw causality repeats perception after blacking out only frames at/after the cut;
prefix features, predictions, candidates and commits must remain equal. Empty
prediction sets and ineffective perturbations are explicitly reported.

No fixed offline delay constant changes without live evidence. Proposed materiality
rule for the later live reconciliation: rerun offline comparisons if measured p95
changes by at least 1 ms **or any commit set changes**. This is a candidate engineering
rule; participant protocol choices remain with the owner.

## Limits

No shipped model, ds-v1.0 fold, live stroke session, acoustic timing, effective-latency
claim, recovery benchmark, calibration wizard or optimization is supplied here.
C-MT and Phase 12 extensions require the pending adoption decision and their declared
gates before live wiring. A cold export call can trip the candidate budget; the
implementation records this instead of hiding warmup costs.

## Amendment — 2026-09-27 (Phase 18 owner decision on live arm B)

Status of this amendment: DECIDED by the owner; implementation PENDING. No code, configuration or
schema has changed, and until the implementation exists the behaviour described above still
applies.

- **Live arm B settings.** In live experiment configurations, arm B runs at the offline-locked B
  settings: the `b_primary` arm of the archived Phase 18 offline lock (motion model, K and step,
  rule parameters, and commit thresholds). For those configurations this replaces "The same
  configured K/step applies to B". No values are chosen here: they exist only after the offline
  lock, which needs `ds-v1.0`.
- **Per-arm commit settings.** The live pipeline gets one set of commit settings per arm (A at its
  Phase 05 settings, B at the locked `b_primary` settings, C at its locked operating point) instead
  of the single shared `commit` block. The alternative, one shared setting declared as a
  deviation, was not chosen, so the Phase 18 pre-registration text needs no change for this
  amendment.
- **Unchanged.** The sticky fallback (owner decision C1, 2026-09-27: no recovery mode, no budget
  change). Its target is still B, which then runs at its locked settings.
- **Before the live lock.** Implementation in `app/pipeline.py` (B's rule settings and the
  per-arm commit policies), the config schema and the live configuration; tests; a check at
  live-lock time that live B and the per-arm commit settings equal the offline lock's arms
  (`live_eval.prereg._live_errors` does not check this today); and re-running the Phase 17 and
  Phase 18 verifications.
