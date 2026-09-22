# Phase 08 — Feature engineering and statistics report

**Date:** 2026-09-22

**Status:** IMPLEMENTED for machinery; participant-fold measurements PENDING

**Primary verification:** `experiments/phase-08/20260922-2115-p08-gate-verification/run.json`

## Evidence boundary

No participant recording, participant label, or human annotation was created. `ds-v1.0` and
its frozen participant splits do not exist. Consequently, this report does not present a
participant sample count, class balance, normalization statistic, descriptive distribution,
or train/validation/test parity claim. Those measurements remain PENDING.

Evidence is kept in separate classes:

- **UNIT / CONTRACT TEST:** deterministic analytic inputs and an in-memory four-identity
  fixture whose identities are named `SYNTHETIC-U*`. These are test identities, not people.
- **SYNTHETIC:** the existing generated session `synthetic-p07-labels`.
- **DEV CAPTURE:** the existing developer capture `dev-p06-ingest-exp-5`.
- **HARDWARE MEASUREMENT (development):** CPU time measured on HW-01 while the Phase 08
  working tree was dirty. This is diagnostic evidence pending a clean owner-commit rerun.
- **PARTICIPANT / MEASURED:** PENDING; no source data exists.

All diagnostic exports use the demonstration parameters N=8, K=4, H=0.1 s, H_max=0.3 s,
stride=1 and g_win=1. The synthetic fold fixture uses stride=2. These execute the exporter;
they are not selected model settings.

## Schema and target contract

The schema is `fs-v1`. Its ordered descriptor and SHA-256 cover group selection, zone layout,
geometry, epsilon, clipping and all feature metadata. The default dimension is `36 + 5Z`:
56 for MVP4 and 71 for the seven-zone layout. Enabling JERK adds three features, giving 59
and 74. Groups are POS, VEL, ACC, optional JERK, AXIS, HAND, ZONE, CONF and TIME.

Trajectory targets contain future positions from the causal track and never feed future data
into X. Strike auxiliaries use Phase 07 labels as targets only. The runtime loader rejects
reference-track filenames/headers, hash or schema mismatches, unfrozen/malformed splits,
participant overlap, session-assignment mismatch, mixed evidence kinds and cross-fold stats.
The NPZ export loads with `allow_pickle=False` and keeps anticipation and safety-only windows
separate.

## Executed diagnostic exports

### Synthetic fold fixture — UNIT TEST

Run `20260922-2122-p08-build-features`; normalization run
`20260922-2122-p08-norm-stats`. Three folds were exported and reloaded. In every fold:

| Partition | Test identities | Total windows | Anticipation | Safety only | Positive | Negative |
|---|---:|---:|---:|---:|---:|---:|
| train | 2 | 452 | 408 | 44 | 40 | 356 |
| validation | 1 | 226 | 204 | 22 | 20 | 178 |
| test | 1 | 226 | 204 | 22 | 20 | 178 |

The remaining anticipation windows have masked auxiliary targets. Fold assignments are
disjoint, stats name only training identities/sessions, the same stats apply to validation and
test, and all composition faults exercised by the tests are rejected. These scripted values
validate mechanics only and are not empirical evidence about class balance or people.

### Existing SYNTHETIC session

Run `20260922-2122-p08-build-features-synthetic` processed 2,262 feature records. Batch and
streaming output were bit-identical for all 2,262 records. Of 2,248 complete history windows,
1,834 were anticipation-eligible and 414 were retained for safety analysis, a diagnostic drop
rate of 0.184164. Eligible auxiliary classes were 1,702 negative and 80 positive, with 52
auxiliary targets masked. Overlapping reason counts were: no future target 64,
segment/quarantine 336, invalid anchor 11, gap threshold 26 and ambiguous target 5.

The same run reports generated-data distributions and time-to-surface/GT-TTI correlations.
Those figures describe the generator. They are not participant descriptive statistics and
must not be used as a scientific result.

### Existing DEV CAPTURE

Run `20260922-2122-p08-build-features-devcapture` processed 342 feature records. Batch and
streaming output were bit-identical for all 342. Of 328 complete history windows, 11 were
anticipation-eligible and 317 were retained for safety analysis, a diagnostic drop rate of
0.966463. All 11 eligible windows have masked auxiliary targets. Overlapping reason counts
were: gap threshold 55, segment/quarantine 302, no future target 173, ambiguous target 65 and
invalid anchor 21. This quarantined developer material is a negative-path diagnostic, not a
participant fold or dataset-quality estimate.

## Normalization and descriptive statistics

The normalization implementation fits eligible training frames once, outside overlapping
windows. VEL/ACC/JERK use median/IQR; other continuous fields use mean/population standard
deviation; angle/direction, confidence flags and time fields use identity scaling. Masked
values remain zero. Each stats file records its fold, dataset and split hashes, source kind,
schema id/hash, training identities and sessions.

The synthetic test folds prove the enforcement path and deliberately produce different
train-only statistics when their training identities differ. Actual per-fold participant
statistics, window counts, speed, inward velocity, zone distance, dt distributions, and
time-to-surface correlation with GT TTI are **PENDING** until `ds-v1.0` and its reviewed,
frozen splits exist.

## Streaming feature latency

Run `20260922-2122-p08-feature-latency` measured 2,000 calls after 200 warmup calls on HW-01
(Intel Core i7-7820HQ, Windows 10 build 22621, Balanced power scheme). Inputs were SYNTHETIC.
Times cover streaming feature computation only; input construction, disk I/O, normalization,
model inference, audio and physical latency are excluded.

| Variant | Dimension | p50 (ms) | p95 (ms) | max (ms) |
|---|---:|---:|---:|---:|
| full with JERK | 74 | 0.9933 | 1.289845 | 2.7599 |
| largest proper group ablation, without TIME | 72 | 1.0230 | 1.8365 | 6.8725 |
| default, without JERK | 71 | 0.97715 | 1.263505 | 2.8962 |

These are real CPU timings on synthetic inputs, but remain **development measurements**
because `git_dirty` is true. A clean committed-tree rerun is condition C-08-3.

## Verification summary

Gate run `20260922-2115-p08-gate-verification` passed all 14 commands on owner SHA
`1a8e790985bc97810eb28bd26ddc788136a16157` with the Phase 08 changes uncommitted:

- focused labels/features/architecture/contracts/scripts: 307 passed;
- full repository regression: 941 passed, 1 opt-in webcam test skipped;
- Ruff, import-linter (7 contracts kept), contract/schema validator, environment smoke,
  pinned model and drum-sample verification, and `git diff --check`: PASS;
- fold export, stats export, DEV CAPTURE replay, SYNTHETIC replay and latency run: PASS.

Three pytest warnings come from deprecated access to `jsonschema.__version__`; they do not
change results. Detailed commands, exit codes, durations, hashes, environment and logs are
stored in the primary verification run.

## Participant measurements still required

After Phase 07 C-07-6 supplies reviewed `ds-v1.0` and frozen participant splits, run the same
export and stats tools on every fold. Report exact per-session and per-partition denominators,
class counts, safety-only reasons, batch/streaming parity across every session, normalization
provenance, train-only distributions and time-to-surface correlations. Until then, Phase 08's
participant-dependent evidence and full Definition of Done remain unsatisfied.
