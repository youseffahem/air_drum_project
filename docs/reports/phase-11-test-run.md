# Phase 11 held-out participant evaluation and ship decision

Status: PENDING. **No test-participant run has been executed, and no model is selected to ship.**

Task 11.9 needs, before any held-out access:

- Phase 09 and Phase 10 gates signed: frozen harness and primary W, participant CV selection
  of the Phase 10 family/N/H, the owner FP budget, FN, timing and CPU bounds (ADR-0025/0027).
- Reviewed ds-v1.0 participant folds with the Phase 08 auxiliary targets.
- Phase 11 CV evidence on those folds: weighting, conflicts, per-task, gating, head ablation,
  intensity source and latency/memory, then one pre-declared C-MT configuration.
- The completed `docs/experiments/phase-11-prereg.md` (δ thresholds, memory budget), archived
  with a timestamp and hashes, and a reserved single-run ledger entry per arm and operating point.

None exists. `scripts/eval_mt.py --partition test` refuses before opening any file (tested:
`tests/temporal/test_mt_protocol.py`). The fixture identity `SYNTHETIC-K0`, held out of every
synthetic fold, is a grouping key of a scripted fixture, not a participant. No synthetic
result in `docs/reports/phase-11-*.md` stands in for this run.

When the prerequisites exist: implement the protocol-specific runner against the archived
addendum, run once for the Phase 10 single-task model, the pre-declared C-MT configuration and
Baselines A/B at their frozen operating points, fill the per-participant metric/CI tables here,
and apply the ship rule of the pre-registration (ADR-0030). Do not re-tune on the results; any
further test analysis is exploratory and labelled as such.

The reproducibility package of a shipped model (clean-environment export reload, metric
reproduction by a second person) is consequently PENDING as well; development exports, hashes,
raw logs and same-environment reproductions exist for every synthetic cell and none is
labelled VALIDATED.
