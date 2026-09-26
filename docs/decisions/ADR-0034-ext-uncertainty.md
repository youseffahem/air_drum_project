# ADR-0034 — E4 predictive uncertainty and the geometry-grounded crossing probability

Status: **IMPLEMENTED contract and machinery; adoption PENDING** participant CV under the
pre-declared rule. Resolves the development layouts of the reserved `TrajectoryPrediction`
`uncertainty` field; the V1 Open Question "per-step uncertainty in V1" stays open until adoption.
Date: 2026-09-26. Related: ADR-0007, ADR-0008, ADR-0018, ADR-0028;
`docs/experiments/phase-12-prereg.md`; `docs/reports/phase-12-e4-uncertainty.md`.

## Context

False positives dominate the development curves (Phase 11 gating report), and the only FP gates
so far are τ_commit, a head probability (Phase 10/11) and agreement checks. Phase 12 Task 12.6 asks
for a *trajectory-first* alternative: propagate the model's predictive uncertainty through the
unchanged geometry and use the resulting crossing probability as a commit gate. `contracts.md`
section 3.6 reserved `uncertainty` (`[K × [m × float]]`) and `uncertainty_kind` for Phase 12.

## Decision

1. **Layouts** (rows per output step; no schema bump, the schema already allows free kinds):
   `sigma_xy` = (std_x, std_y) of an independent-axis Gaussian around `positions`;
   `members_xy` = member offsets from `positions` (equal weights);
   `mixture_xy` = (w, dx, dy) per mode, weights repeated per step (E2c development encoding, see
   ADR-0032). Encoders: `models/temporal/ext/uncertainty.py`; decoder and propagation:
   `geometry/probabilistic.py`. A round-trip test binds the two.
2. **Propagation** (`geometry/probabilistic.py`, additive; `intersect.py` unchanged): weighted
   sample polylines from the current tip; the unchanged `first_impact` per sample; earliest impact
   over the hand's zones as in `GeometryEngine.intersect`; per-zone probability and TTI quantiles.
   Gaussian samples: S = 32 antithetic common random numbers (seed 1212), one draw per sample
   shared by all steps. A prediction without uncertainty is one certain sample and reproduces the
   deterministic candidate exactly (tested); a known analytic case reproduces 1 − Φ(d/σ).
3. **Commit use** (`CrossingProbabilityGate`, the replay's post-geometry hook): the candidate
   zone's crossing probability replaces the geometry candidate's null `strike_probability`; the
   unchanged Phase 05 `p_commit` then gates it. The gate never creates a candidate; the candidate
   still comes from the point trajectory. The current tip is recorded by the caller at prediction
   time (same frame; `eval/probabilistic.AnchorRecorder`); in Phase 13 the pipeline has it anyway.
4. **Declared variants**: E4(a) `e4-gauss` (Gaussian head; mean trained by the Phase 10 Huber loss,
   log σ by Gaussian NLL of the detached mean's residuals; shared encoder) and E4(b) `e4-ens3`
   (per-fold ensemble of the three reference seeds). Quantile regression and MC-dropout were not
   attempted (entry decision).
5. **Calibration** is reported (reliability, ECE, Brier, ROC-AUC against `strike_within_H`), never
   deciding. Whether the crossing probability should *replace* τ_commit gating stays an Open
   Question; the control grid includes τ ≥ H points, where only the probability gates.

## Alternatives considered

- Analytic crossing probability: exact only for special geometries (straight paths, a single
  segment surface); Monte-Carlo through the real impact test keeps one impact definition.
- Independent per-step draws: available (`correlation="independent"`) and tested, not declared,
  because trajectory errors of one prediction are strongly correlated along the horizon (a wrong
  velocity estimate displaces every later step), which independent noise ignores.
- A dedicated `modes` field now: deferred to adoption of rule M2 (schema bump + ADR then).

## Consequences

- No contract, geometry-file or commit change; the live pipeline can adopt the gate without new
  data paths. CPU cost grows with S × zones on candidate frames; the go/no-go rule measures it.
- Development observations (SYNTHETIC; `docs/reports/phase-12-e4-uncertainty.md`): `e4-gauss`
  degraded the mean trajectory and failed the CPU factor for TCN (3.55 ×); `e4-ens3` improved
  trajectory error and calibration without a rule-level lead gain. An EXPLORATORY post-hoc variance
  head (not pre-declared) kept the mean exactly and let the gate move GRU cells inside the budget
  (5/12 vs 2/12); the submitter proposes declaring it as E4(a′) before participant CV (owner
  decision). They do not decide adoption.
