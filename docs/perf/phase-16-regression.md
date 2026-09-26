# Phase 16 regression protocol

Status: **PENDING** clean reproduction and participant evidence. Protocol declared
2026-09-26 (+03:00), before optimization.

## Fixed inputs and tolerances

The raw roster is `configs/perf.regression-plan.json`: all 514 frames in the three
existing developer swing captures (171, 171, 172). The model and normalization are
pinned by `configs/perf.developer.candidate.yaml`, copied from the Phase 13 parity
configuration. Fallback is disabled only in this replay comparison so machine
scheduling cannot silently change the arm. Live safety checks retain fallback.
The reference run saves image, frame-stream, model, validation archive and source
hashes, complete ordered records and Phase 09 harness outputs.

| Quantity | Acceptance tolerance declared before optimization |
|---|---|
| Tracks and features | Exact |
| Predictions and candidates | absolute 1e-6 + relative 1e-5; timestamps absolute 1e-6 s only |
| Commits | Identical ordered complete records, including arm, hand, zone, time and candidate link |
| Synthetic validation ADE/FDE and per-step errors | export tolerance, absolute 1e-6 + relative 1e-5 |
| Harness event metrics | Exact; lead median must therefore also be within 1 ms |
| Explicit exclusions | wall-clock inference/candidate stamps and config/model content hashes; changed hashes remain recorded as provenance |
| Real participant fold | PENDING; unavailable reviewed ds-v1.0 is never replaced by a synthetic result |

The delay is identical in before/after comparisons: original capture-to-available
interval, with zero added processing delay. Timing changes are assessed separately.
No timing-shift waiver is automatic. A faster candidate failing this protocol is
rejected. No retraining, test-partition opening or participant collection is authorized.

The pinned model was trained on SYNTHETIC data. Its hashed 202-window validation
archive and the matching synthetic validation session exercise trajectory metrics
and the unchanged Phase 09 event harness. These are engineering regression checks,
not research results or a participant fold. Developer recordings have no reviewed
impact ground truth, so their prediction/commit equality is checked without inventing
lead-time or accuracy labels.

## Measurement plan

- Three fresh runs of every raw session for baseline and retained optimizations;
  include startup and report per-run distributions as well as pooled per-frame values.
- Profile allocations/cProfile separately; those timings are perturbed and cannot
  establish a speedup. Native thread CPU counters are sampled once per second;
  these counters do not directly measure GIL contention.
- Screen half-resolution hand detection (full-resolution stick processing), a single
  synchronous perception worker, IMAGE landmark mode, OpenCV thread count, and
  allocation reductions. Each experimental switch is scoped to its process/run.
- Evaluate frozen TorchScript and dynamic int8 packages with the same weights and
  validation samples; separately hash every candidate. Adoption needs full regression.
- Live unattended before/after checks are bounded at 30 seconds. No person is available.
  A 300-second unattended camera/audio/dashboard soak is the candidate duration;
  sustained strokes, polyphony and participant use remain for later owner evidence.
- At least 1 ms p95 processing change or any changed commit set triggers delay-policy
  review (Phase 13 candidate materiality rule). Replay or an idle-camera run cannot
  establish a representative live-stroke processing constant.

Results and exact run references are recorded in the profiling report and perf log.

## Executed comparisons

Frozen reference: `experiments/phase-16/20260926-1301-reference-fixed/snapshot.json`,
SHA-256 `35f095b4664e94e6ce90127feffd78e167d87d0c86aefc84ee6612935b13e26d`.
The three raw captures have 424/166/0 prediction records and 11/0/0 commits across
the active/shadow arms. The third capture is an absence case and cannot alone
establish behavioral preservation. Full hashes and records remain in the snapshot.

OpenCV 1, component bounds, arc cache, thread and process comparisons pass the
declared tolerances. Half resolution and IMAGE mode fail and are rejected.
`20260926-1313-process-regression`, `20260926-1322-zones-regression` and
`20260926-1336-thread-causality` additionally preserve 85/85/86-frame prefixes
under future-image blackout. Changed suffix counts are 86/12/0; the first two
sessions exercise a meaningful perturbation, while the absence case is vacuous.
Final retained-source verification is linked from the gate record.

The order-preserving frozen graph comparison
`20260926-1334-frozen-ordered-regression` passes. The int8 comparison
`20260926-1335-int8-ordered-regression` fails: first-capture commits become 13
instead of 11 and the synthetic harness's false positives become 6 instead of 4.
See the model-cost report for preserved initial config-order-confounded trials.

### Synthetic metric interpretation

The reference validation ADE/FDE is 0.0717297271 normalized units on 198 valid
points from the 202-window archive. These values are identical for retained
changes and the frozen graph. Int8's ADE/FDE is 0.0687823370: even a smaller
trajectory error does not waive changed records or a failed export tolerance.

The reference synthetic event harness has 0 matched impacts, 4 false positives
and 6 false negatives over 3.481 seconds of active time. Its lead median is
**undefined**, not zero. Equality of null fields does not validate a 1 ms lead
band; that criterion remains PENDING on informative reviewed data. No synthetic
result is promoted to a participant result or evidence of useful lead time.
