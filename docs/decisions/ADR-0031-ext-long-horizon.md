# ADR-0031 — E1 longer horizon and the two-rate output grid

Status: **IMPLEMENTED machinery; adoption PENDING** participant CV under the pre-declared rule.
Date: 2026-09-26. Related: ADR-0026 (horizon, fixed-grid targets); `docs/experiments/phase-12-prereg.md`;
`docs/reports/phase-12-e1-long-horizon.md`.

## Context

Useful lead is bounded by H − Δ_proc. The Phase 10 horizon grid stops at K = 4 (H = 0.133 s at
dt = 1/30 s). Task 12.3 asks whether longer horizons, possibly with coarser far steps, add lead
without an FP explosion.

## Decision

1. Candidates `e1-k6` (K = 6, H = 0.2 s), `e1-k8` (K = 8, H = 0.267 s) and `e1-2rate` (outputs at
   steps 1, 2, 3, 4, 6, 8: fine near steps, 2·dt far steps, H = 0.267 s, 6 outputs).
2. Targets come from the unchanged Phase 10 fixed grid up to the largest step; the two-rate grid
   selects columns of that dense grid, so no new interpolation exists
   (`models/temporal/ext/long_horizon.py`, tested). Windows are re-exported per horizon by the
   Phase 08 exporter (H_max 0.3 s).
3. Two-rate predictions carry explicit `t_offsets_s` (field present since TrajectoryPrediction
   1.0); geometry intersects the polyline as given (contracts.md section 3.6; tested).
4. The τ_commit grid extends to 0.20 s for every variant, including the reference, so that a
   longer horizon can be exploited and FP growth is visible.
5. Participant CV runs E1 only if the Phase 10 participant horizon sweep selects its largest K or
   shows lead bounded by H − Δ_proc (entry decision).

## Alternatives considered

- K > 8: limited by the fixture's H_max = 0.3 s and by FDE growth; not declared.
- Three-rate or learned offsets: more machinery for the same question; not declared.

## Consequences

- No contract change. A longer adopted H would change the live prediction clock (ADR-0026) and the
  Phase 13 Δ_proc budget discussion.
- Development observations (SYNTHETIC; `docs/reports/phase-12-e1-long-horizon.md`): every E1
  variant NO-GO (TCN) or insufficient evidence (GRU); development picks stayed at τ ≤ 0.05 s, so
  the FP budget, not H, bounded lead on the fixture. They do not decide adoption.
