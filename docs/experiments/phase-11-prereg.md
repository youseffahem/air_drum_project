# Phase 11 pre-registration addendum

Status: PENDING — draft addendum to `phase-10-prereg.md`, not an approved participant
pre-registration. Created 2026-09-25 (+03:00). No held-out Phase 11 evaluation has run.

Everything fixed by the Phase 10 protocol applies unchanged: participant folds and the reserved
test roster, matching W, Δ_proc delay policy, FP budget, FN ceiling, timing and CPU bounds,
operating-point rule, bootstrap over participants, seed aggregation and the single-run
ledger. Those fields are themselves PENDING (Phase 09/10 gates, ds-v1.0, owner budgets); this
addendum cannot be completed before them. Preserve a timestamped, hashed copy of the completed
addendum and every selected configuration before any held-out access.

## Candidates

- Encoder: the family, N, H (K × dt_step) and size selected by Phase 10 (PENDING); all heads share
  it. Heads: trajectory (primary, unchanged loss/decoding), strike-within-H (BCE on
  `strike_mask`), TTI (direct / log / bins, scaled by H_max, masked to an impact within H_max),
  zone (cross-entropy over the declared zone ids, masked to impacts), impact position
  (L1 or L2 on the displacement from the current tip, masked), intensity (Huber on
  train-fold-standardised `intensity_proxy_gt`, masked). No imputation; masks are per sample
  per task.
- Checkpoint criterion: Phase 10's participant-macro validation ADE whenever the trajectory
  head exists (a head cannot change the stopping rule). The no-trajectory diagnostic uses the
  unweighted validation head loss.
- Loss weighting: fixed (all λ=1; auxiliary λ=0.3), trajectory-dominant (λ_traj=1, others
  0.05), uncertainty (learned log-variances, regulariser only for tasks labelled in the batch)
  and GradNorm (α=1.5, weight lr 0.025, last shared layer). Candidate values, not tuned.
- Gates (`commit.aux_heads`, config 1.5; all off by default): none; `p_aux` ∈ {0.3, 0.5, 0.7};
  agreement on {zone, TTI, position} with tight (TTI 0.02 s, position 0.03) and loose
  (0.05 s, 0.06) tolerances; both (p_aux 0.5 + agreement). Intensity source: geometry
  (inward crossing speed on the predicted trajectory) or head, scored at the commit.
- Head ablation: trajectory-only (bit-identical to the Phase 10 single-task model), +strike,
  +TTI, +zone, +position, +intensity, all heads, and the no-trajectory diagnostic
  (strike + TTI + zone heads → DIRECT_HEAD candidate, same commit policy, labelled
  *direct / no-trajectory (diagnostic)*; never a ship candidate).
- At least three seeds per variant/fold; the same folds and seeds for every variant.

## CV procedure (validation participants only)

1. Weighting: exclude any scheme whose paired ADE or FDE change against trajectory-only
   exceeds 2 × the pooled within-fold seed SD of trajectory-only (degradation beyond seed
   variance). Among the rest, choose the highest participant-macro median lead at the Phase 10
   FP budget; ties → lower ADE → simpler scheme (fixed, dominant, uncertainty, GradNorm).
2. Conflicts: sampled per-task gradient cosine with the trajectory task on shared encoder
   parameters. A head whose inclusion degrades ADE, FDE, lead at budget or FP/min beyond seed
   variance is flagged and excluded from the ship candidate unless a gate needs it.
3. Per task: each head against the geometry-derived answer on the same trajectory and against
   Baseline B, on covered rows, stratified by true TTI; coverage reported.
4. Gates: choose the gate (or none) that maximises lead within all Phase 10 budgets; report
   ΔFP and ΔFN against no gate at equal τ_commit; a gate that only trades lead for FP stays on
   the curve, not in a headline.
5. Intensity: at the commit of matched strikes, compare geometry, head and Baseline B's
   extrapolated crossing speed with `intensity_proxy_gt` (Spearman ρ primary, MAE, Pearson r).
   Choose the source with the higher participant-macro ρ if its CI excludes the other's
   estimate; otherwise keep geometry (no learned dependency). Record in ADR-0029.
6. Latency/memory: batch-1 p50/p95/p99 (windowed; bounded stateful for GRU), parameters,
   export bytes and working set, MT versus single-task, on the target CPU.

## Ship-decision rule (Task 11.9, ADR-0030)

Pre-declare one C-MT configuration (heads, weighting, gate, intensity source, operating point)
from the CV procedure. On the held-out participants, run once, beside the Phase 10 single-task
model, Baseline A and Baseline B, at their predeclared operating points. Then:

1. Discard any arm that violates the FP budget, FN ceiling, timing-MAE bound or CPU p95 bound.
2. Ship C-MT instead of single-task only if (a) its participant-paired lead difference has a
   95 % bootstrap CI lower bound above −δ_lead (non-inferior), **and** (b) at least one of FP/min,
   zone accuracy or intensity agreement improves by at least its δ with a CI excluding zero,
   **and** (c) latency and memory stay within budget. Otherwise ship the single-task model; if
   it is infeasible and Baseline B is feasible, ship B.
3. Heads not used by the shipped gate or intensity source are informational; drop them if
   their removal reduces p95 latency by more than δ_cpu.

| Field | Status |
|---|---|
| Phase 10 selected family/N/H/operating point | PENDING Phase 10 CV and gate |
| FP budget, FN ceiling, timing and CPU bounds | PENDING owner (ADR-0025) |
| δ_lead, δ_fp, δ_zone, δ_int, δ_cpu, memory budget | PENDING owner |
| TTI parameterisation and head sizes | To Be Experimentally Determined (CV) |
| Weighting, gate, tolerances, intensity source | To Be Experimentally Determined (CV) |
| Pre-declared C-MT candidate and ledger entry | PENDING all rows above |

## Held-out access and reporting

`scripts/eval_mt.py --partition test` refuses before opening any file; the confirmatory runner
is implemented only against the completed, archived protocol, never as a generic sweep. No
re-tuning on test participants; any further test analysis is exploratory and labelled as such.
Report outcome-neutrally: multi-task better, no material difference, or worse. SYNTHETIC or
DEV CAPTURE results never enter this protocol's tables.
