# Phase 04 geometry and audio implementation report

**Status:** IMPLEMENTED with automated evidence; physical output latency **PENDING**\
**Code state:** base `d6bc0ba97369f53e6ed12bd3e9c5ecf0e6974321`, dirty Phase 04 tree (no commit requested)

## Task evidence

| Task | Result | Evidence |
|---|---|---|
| 04.1 registry/layouts | IMPLEMENTED | 4-zone and 7-zone candidate fragments; schema + object validation tests |
| 04.2 shapes/surfaces | IMPLEMENTED | rotated ellipse, polygon, segment/arc, boundary and inward-normal tests |
| 04.3 intersection | IMPLEMENTED | analytic segment/segment and segment/arc tests; crossing error bounded by 1e-12 s in the test assertions |
| 04.4 entry/episodes | IMPLEMENTED | inward-speed gate, side/upward rejection, hover suppression, leave/re-enter, invalid reset tests |
| 04.5 predictions | IMPLEMENTED | `t_impact_pred`, TTI, start-inside behavior and observed/predicted equivalence tests |
| 04.6 samples | IMPLEMENTED | hash-verified, resampled public-domain prerecorded TR-505 bank; synthetic bank retained as test-only |
| 04.7 device/mixer | IMPLEMENTED | device clock regression, sample-offset placement, polyphony, carry-over, late and xrun tests; actual callback attempts |
| 04.8 scheduler | IMPLEMENTED | future/past target and shadow refusal tests; `AudioEvent` schema validation |
| 04.9 output latency | machinery IMPLEMENTED; evidence PENDING | `docs/audio-profile-hw01-realtek.md`; noisy/unknown-tap runs rejected |
| 04.10 gain | IMPLEMENTED | monotonicity and clipping tests for linear and power curves; proxy documented as kinematic, not force |
| 04.11 rendering | IMPLEMENTED + development MEASURED | `20260921-1527-p04-layout-render`; inspected screenshot in `docs/figures/phase-04/` |

## Measurements and labels

| Quantity | Value | Label / evidence |
|---|---:|---|
| Analytic crossing-time numerical error | <= 1e-12 s in assertions | SYNTHETIC analytic test evidence |
| Geometry + scheduling compute, p50 / p95 | 0.03970 / 0.07280 ms | MEASURED development, SYNTHETIC input, `20260921-1536-p04-geometry-schedule-cost`, dirty tree |
| Overlay compute, p50 / p95 | 2.7022 / 4.9779 ms for 960x720 blank ROI | MEASURED development, SYNTHETIC input, `20260921-1527-p04-layout-render`, dirty tree |
| Device-clock mapping residual RMS | 0.004300 s, 2,888 samples | MEASURED development on HW-01, `20260921-1537-p04-audio-loop-b128`, dirty tree |
| Callback xrun status | 0 in each short 35-click B=64/128/256/512 attempt | MEASURED development only; run ids in audio profile; not an underrun-rate validation |
| Audio output latency median / p90 | no accepted value | **PENDING**; no valid post-DAC synchronized capture |
| Chosen buffer | none | **PENDING**; 128 remains a candidate, not evidence-based selection |

No number above is participant data, accuracy, robustness, physical ground truth, or real-world
validation. No participant recordings were requested or created. The actual audio attempts are
device measurements only; raw audio was not persisted.

## Final validation (post patch-integrity audit)

Final run on HW-01, 2026-09-21, dirty tree, after the whitespace normalization recorded in
`docs/gates/phase-04-gate.md` §3.1:

| Check | Result |
|---|---|
| Focused Phase 04 pytest (geometry, audio, config, contracts, script self-tests) | 208 passed, 71.56 s |
| Full project pytest | 402 passed, 1 skipped (opt-in webcam test), 102.08 s |
| `ruff check .` | All checks passed |
| `lint-imports` | 4 contracts kept, 0 broken (50 files, 103 dependencies) |
| `scripts/validate_contracts.py` | PASS, 15 schemas |
| `scripts/env_smoke.py` | PASS |
| `fetch_hand_landmarker_model.py --verify`, `fetch_drum_samples.py --verify` | PASS, PASS (7/7) |
| `git diff --check` including untracked files | clean |
| `generate_sample_bank.py` determinism | manifest and 7 WAVs byte-identical to `assets/samples/` |

Normalization changed no behaviour: the only code edit was `newline="\n"` on the manifest write
in `scripts/generate_sample_bank.py` so the tracked manifest is LF on every platform. Run
`20260921-1528-p04-audio-b128` (bimodal Stereo Mix attempt, previously unlisted) was added to the
audio profile as **rejected**; run `20260921-1535-p04-geometry-schedule-cost` is an aborted directory
without `run.json`, superseded by `…-1536-…`. Neither changes any label above.

## Causality and scope

Observed geometry uses exactly `(p[i-1], p[i])`. Prefix-invariance is tested. Predicted geometry
uses only the supplied ordered trajectory and never creates missing steps. Tracking `INVALID` or
`STALE` terminates the entry episode. No commit policy, refractory logic, anticipation model, MIDI,
kick zone, realistic kit UI, or Phase 05 work was added. `hands.swap_handedness: false` is unchanged.

## Limitations and pending decisions

- Zone positions, sizes, `v_min`, and gain bounds remain candidate values for Phase 05/07/14.
- The seventh V1 zone is represented as a candidate Ride split; owner decision remains open.
- Tilted cymbal surfaces are supported and used in the candidate layouts; whether they improve play
  remains a Phase 05 playtest question.
- Backend and buffer selection remain Pending Benchmark because output latency was not measured.
- All timing/profile runs are dirty-tree development evidence because this run was explicitly not
  allowed to commit. Clean-tree reproduction is a gate condition.
