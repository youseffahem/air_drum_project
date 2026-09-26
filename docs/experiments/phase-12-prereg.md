# Phase 12 pre-registration addendum — extension go/no-go rule (Task 12.2)

Status: PENDING — draft addendum to [`phase-10-prereg.md`](phase-10-prereg.md) and
[`phase-11-prereg.md`](phase-11-prereg.md), declared 2026-09-26 (+03:00) **before any Phase 12
extension was trained or evaluated**. It is not an approved participant pre-registration. The
Phase 10 fields it inherits (FP budget, FN ceiling, `W`, Δ_proc policy, timing bound, CPU bound)
are themselves PENDING. Scope and priorities: [`phase-12-entry-decision.md`](phase-12-entry-decision.md).
Archive a timestamped, hashed copy of this file and of every selected configuration before any
participant CV run and again before any held-out access.

## Reference

The reference for every extension is the Phase 10/11 selected (shipped) configuration: family, N,
H, size, final-fit recipe and operating-point rule (ADR-0027, ADR-0030), PENDING. Until it exists,
development runs use the Phase 10 trajectory-only GRU **and** TCN at the development configuration
of the entry decision, trained by the unchanged `models/temporal/train.train_fold`. Each extension
is compared with the reference of the same family on the same folds and seeds (paired). The
Tiny Transformer (its own family) is compared with both reference families.

## Invariants (not negotiable by any result)

1. **Causality.** Every new encoder, head, decoder and uncertainty propagation consumes only
   observations with timestamp ≤ the current frame's `t_capture`. Attention masks every future
   position; no bidirectional or future-attending layer exists under any name. TEST-CAUSAL-1/2 pass
   for every new component before any result derived from it is reported.
2. **Trajectory first.** Every candidate comes from the unchanged Phase 04 impact test on a
   predicted *point* trajectory (the mean, or the most probable mode). Uncertainty, mixture weights
   and crossing probabilities may only **relabel** a geometry candidate's `strike_probability`
   (which the unchanged Phase 05 `p_commit` then gates) or drop it; they never create one.
3. **Same protocol.** Same folds, seeds, `W`, Δ_proc policy, FP budget, FN ceiling,
   operating-point selection rule (`eval.selection.select_point`, Phase 10 pre-registration),
   geometry, commit policy and harness as the reference.
4. **Independence.** Each extension variant is evaluated alone against the reference.
   Combinations are built only from individually adopted variants (recorded as a new variant).
5. **Held-out data.** No test participant is opened during CV. One confirmatory run per adopted
   configuration (Task 12.8); no re-tuning after it.

## Declared variants (fixed before any run)

| Id | Extension | Definition | Trained? |
|---|---|---|---|
| `ref` | reference | Phase 10 displacement head, K = 4, dt = 1/30 s | yes (Phase 10 code path) |
| `e1-k6`, `e1-k8` | E1 | displacement head, K = 6 / 8 uniform steps | yes |
| `e1-2rate` | E1 | 6 outputs at steps (1, 2, 3, 4, 6, 8)·dt, emitted with `t_offsets_s` | yes |
| `e2-vel` | E2(a) | per-step increments, positions by cumulative sum; velocities = increment/Δτ | yes |
| `e2-poly` | E2(b) | p(τ) = Σ_{d=1..3} c_d (τ/H)^d per axis; analytic velocities | yes |
| `e2-mix2` | E2(c), rule M1 | 2 modes + logits; relaxed winner-takes-all (ε = 0.05) + 0.5 × cross-entropy on the winning mode; point = most probable mode; probability null | yes |
| `e2-mix2-agg` | E2(c), rule M2 | the `e2-mix2` models; candidate from the most probable mode, `strike_probability` = Σ_m w_m·1[mode m's first valid impact lies in the candidate's zone] | no (rule) |
| `e3-tt` | E3 | causal Tiny Transformer, width 16, 2 heads, 2 layers, FF 32, learned relative-position bias, displacement head | yes, **only if feasible** |
| `e4-gauss` | E4(a) | mean (Phase 10 Huber) + per-step log σ_x, σ_y (Gaussian NLL on the detached mean residual); layout `sigma_xy` | yes |
| `e4-ens3` | E4(b) | per fold, the three reference seeds as an ensemble: point = member mean; layout `members_xy`; compared per fold with the reference seed mean | no (reuses `ref`) |
| `e5-resb` | E5(a) | point = causal CV extrapolation v·τ of the current frame's velocity features (train-fold de-normalised) + learned residual | yes |
| `e5-smooth` | E5(b) | reference models; decoded points projected so that ‖Δ²p‖/Δτ² ≤ a_max from the second step on; a_max = 99th percentile of that quantity on the fold's **training** targets | no (reuses `ref`) |

Crossing probability (E4, M2): common random numbers, S = 32 antithetic standard-normal draws
(seed 1212), shared across the steps of one sample ("shared" correlation), equal weights; members or
modes are used as given with their weights. The unchanged Phase 04 `first_impact` is applied to
each sampled polyline from the current tip; the earliest impact over the hand's zones decides the
sample's zone, as in `GeometryEngine.intersect`. Relabelling uses the candidate zone's
probability. Variant `e4-gauss` and `e4-ens3` relabel; `ref` and the other variants carry null.

## Control grid (every variant)

τ_commit ∈ {0.02, 0.05, 0.10, 0.15, 0.20} s (the longer values let an extended horizon be used);
`p_commit` = 0 for null-probability variants and ∈ {0, 0.3, 0.5, 0.7} for relabelling variants
(0 = gate off); n_confirm 0; inward speed floor 0.15 ROI/s; zone refractory 0.10 s. The reference
uses the same τ grid.

## Primary criterion

Per trained cell (family × fold × seed): the participant-macro median `L_pred` at the operating point
chosen on that fold's validation participants by the Phase 10 rule, subject to the FP budget and
FN ceiling (`select_point`). A cell without a feasible point has no primary value.

## Go/no-go rule (mechanical; per variant and family)

**GO (adopt)** only if all of the following hold on participant CV folds:

1. **Feasibility.** The variant has a budget-feasible point in at least as many cells as the
   reference.
2. **Lead.** The mean paired difference (variant − reference; same family, fold and seed; per fold
   against the reference seed mean for `e4-ens3`; against each reference family for `e3-tt`) in the
   primary criterion, over cells feasible for both, exceeds **2 × the reference's pooled within-fold
   seed SD** of the primary criterion (the seed-variance band). If that band is undefined (fewer
   than two feasible seeds in any fold) the outcome is **NO-GO (insufficient evidence)**.
3. **Timing.** The mean paired difference in `TE_pred` MAE at the selected points is
   ≤ max(2 × the reference's pooled within-fold seed SD of that MAE, δ_TE). δ_TE (absolute timing
   tolerance) = owner value, PENDING with the Phase 10 timing bound.
4. **CPU.** The p95 batch-1 latency of the variant's inference-to-candidate path (model forward,
   decoding, geometry, and probabilistic geometry where used), measured on the frames where its point
   trajectory yields a candidate, is within the Phase 13/16 budget if known. Otherwise it must be
   ≤ **F × the reference's p95 of the same path in the same isolated session** on the target CPU,
   with **F = 3**. For E3, the feasibility gate precedes training: a randomly initialised TT
   forward pass p95 ≤ F × max(GRU, TCN reference forward p95), all three random-initialised,
   TorchScript, batch 1, one thread, in one isolated session.

Otherwise **NO-GO**. ADE/FDE, best-of-M error, calibration and zone accuracy are reported but never
decide: an extension that improves ADE but not lead at the FP budget is not adopted. An extension
that is GO for one family only is adopted only for the family of the selected reference.

## Multi-modal commit rule (E2c)

Rule M1 (primary) and rule M2 are both evaluated. Each counts as a separate variant under the rule
above. If both are GO, M1 is adopted (no probability dependency) unless M2's lead difference over
M1 exceeds the same seed-variance band. Adopting M2 requires the `modes` contract field
(schema bump + ADR) in place of the development `mixture_xy` layout.

## Calibration (E4, M2; reported, not deciding)

On validation windows with `strike_mask`, the crossing probability over all zones is compared with
`strike_within_H` (H = the model's horizon). Report a reliability diagram (10 equal-width bins),
expected calibration error, Brier score and ROC-AUC. The reference's deterministic crossing
indicator (0/1) is the comparator. Poor calibration with few positives is reported, not tuned.

## Confirmatory run and shipping (Task 12.8; only for GO variants)

One held-out run of each adopted configuration beside the reference, Baseline A and Baseline B at
their frozen operating points. Ship the extension instead of the reference only if its
participant-paired lead difference has a 95 % participant-bootstrap CI lower bound above
−δ_lead (the Phase 11 owner value) with a positive point estimate, and the FP, FN, timing and CPU
bounds hold. Otherwise keep the reference. The reproducibility package and ship ADR are then updated.

## Owner / evidence fields

| Field | Status |
|---|---|
| Selected Phase 10/11 reference | PENDING (ADR-0027, ADR-0030) |
| FP budget, FN ceiling, `W`, Δ_proc policy | PENDING (Phase 09/10) |
| δ_TE, δ_lead | PENDING owner |
| Phase 13/16 CPU budget | PENDING; F = 3 applies until then |
| Participant failure catalogue re-ordering of priorities | PENDING Phase 10 Task 10.12 |
| Compute/time budget for participant CV | Open Question (owner) |

## Development (SYNTHETIC) application

The development runs apply this rule mechanically with the Phase 11 development constants
(FP 30/min, FN 0.6; `scripts/_p11.py` `DEV_BUDGET`), δ_TE = 0 and the CPU rule measured on HW-01.
Their outcomes are labelled **development verdict (SYNTHETIC; not an adoption decision)** and only
check the machinery. SYNTHETIC or DEV CAPTURE results never enter this protocol's participant tables.
