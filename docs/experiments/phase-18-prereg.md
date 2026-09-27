# Phase 18 pre-registration — confirmatory A / B / C evaluation (offline and live)

Status: **DECLARED — owner and supervisor approval PENDING.**

- Declared 2026-09-27 (+03:00) by the Phase 18 submitter (Claude Opus 5.5 via Claude Code, acting for
  the project owner).
- Archived by SHA-256 in [`phase-18-prereg.hashes.json`](phase-18-prereg.hashes.json) before any
  Phase 18 runner was executed on any data.
- No confirmatory run has taken place: the reviewed `ds-v1.0` dataset, the frozen `W`, the
  processing-delay policy, the owner budgets, the operating points and the shipped model do not
  exist yet (§12).

Scope: Task 18.1 of [`phases/phase-18-evaluation-experiments.md`](../../phases/phase-18-evaluation-experiments.md).
Definitions: `phases/README.md` §5 (timestamps and latencies), §6 (events), §9 (arms) and §10
(metrics), used verbatim. Earlier protocols this document builds on:
[`phase-10-prereg.md`](phase-10-prereg.md), [`phase-11-prereg.md`](phase-11-prereg.md),
ADR-0023 (matching), ADR-0024 (operating points), ADR-0025 (FP budget), ADR-0027 / ADR-0030 (model
selection and shipping).

## 0. How this pre-registration works

The protocol has two stages. The rules are fixed now; the numbers are fixed later, before any
confirmatory data is read.

1. **This document** fixes the hypotheses and their failure readings, the arms, the metrics, the
   matching, the statistics, the decision rules, the exclusion rules, the live design, the
   acceptance rules for the external measurement methods, and the tables and figures.
   - Its SHA-256 is appended to `phase-18-prereg.hashes.json` with a timestamp.
   - Every Phase 18 runner refuses to start when the file on disk differs from the latest archived
     version.
2. **Upstream values** (dataset, `W`, `Δ_proc`, budgets, operating points, model packages, method
   uncertainties) appear here only as symbols. They are written into two **frozen-inputs locks**
   (schema `schemas/confirmatory-lock.schema.json`):
   - the *offline lock*, before Experiment 1;
   - the *live lock*, before the first live participant session.

   Each lock records the source of every value, is validated by `scripts/confirmatory_lock.py`, and
   has its hash appended to the same record before use. A lock with a missing or placeholder field
   cannot be archived.
3. **Amendments.**
   - Before a lock is archived: allowed, as a new archived version with date and reason.
   - After a lock is archived, or after the confirmatory runner has read any test-participant data:
     only as a **new pre-registered run**, reported as such beside the original. Never a silent
     replacement.
4. **Approval.** The owner, and the supervisor where the institution requires it
   (`docs/gates/gate-procedure.md` §1), approve a specific archived version by its hash
   (`scripts/prereg_archive.py approve`). Until then this document is a declared draft. It cannot
   authorise a confirmatory run on its own: a participant lock is refused, at archiving and at run
   time, unless the latest archived version carries an approval entry.

## 1. Question and experiments

> Can a small causal temporal model predict the future trajectory and imminent virtual impact of an
> ordinary drumstick early enough to reduce effective Action-to-Sound Latency compared with reactive
> impact detection, while maintaining acceptable false-positive and timing-error behaviour?
> (`phases/README.md` §1)

| Experiment | Data | Decides |
|---|---|---|
| 1. Offline confirmatory | `ds-v1.0` held-out test participants, run **once** through the frozen Phase 09 harness | H1, the C-vs-B comparison, H2, H3 |
| 2. Live end-to-end timing | new live sessions: developer pilot, then consenting live participants | H4, H4-B; live FP / FN / `L_pred`; software decomposition |
| 3. Questionnaire (optional) | the same live participants | nothing: descriptive only |

Whether Experiment 3 is included is an **Open Question**: time and ethics scope, decided by the owner
before the first live session. The draft instrument is
[`../protocols/phase-18-questionnaire.md`](../protocols/phase-18-questionnaire.md).

## 2. Arms

| Arm id | Definition | Operating point |
|---|---|---|
| `A` | Reactive detection (Phase 05 settings, ADR-0018) | Phase 05 commit settings (no knob) |
| `B-CV`, `B-CA` | Rule-based anticipation, constant velocity / constant acceleration | ADR-0024 selection on validation folds, run separately per motion model |
| `B` | Whichever of `B-CV` / `B-CA` has the higher validation median lead at its feasible point. Ties: lower FP/min, then CV. | as its source arm |
| `C-GBDT-direct`, `C-GBDT-traj` | Phase 09 GBDT: direct heads, and the trajectory-derived path through geometry | ADR-0024 rule, applied per mode |
| `C` (primary) | The temporal model shipped by ADR-0030 (single-task or C-MT). If ADR-0030 ships none, the Phase 10-selected temporal model (ADR-0027), evaluated and labelled **not shipped**. | Phase 10 selection rule (`phase-10-prereg.md`) on validation |
| `C-2` (optional) | The other temporal model if ADR-0030 keeps both. Secondary, descriptive. | as `C` |

Rules for the arm set:

- The C-MT *direct / no-trajectory* diagnostic is **not** an arm; it belongs to Phase 19. Every C
  candidate goes through the unchanged geometry and commit policy (ADR-0007).
- All arms share one set of inputs: participants, sessions, labels, `W`, geometry, commit
  implementation, active-time denominators, delay policy and harness version.
- Live arms (Experiment 2): `A`, `B` and `C`. Exactly one arm sounds. The other two run in shadow
  (logged, never scheduled). C-GBDT is not wired into the live application and is offline only.

## 3. Hypotheses, decision rules and failure readings

### 3.1 Notation

- `m_X(p)` is metric `m` of arm `X` for participant `p`, at the arm's frozen operating point,
  computed over all of `p`'s test sessions (matching per session and hand; metrics over the union of
  `p`'s matched pairs, false positives and active time).
- **Macro estimate:** the mean over participants.
- **CI:** the 95 % percentile bootstrap over participants (§6).
- **Paired difference:** `d(p) = m_X(p) − m_Y(p)` over the participants for whom both values are
  defined.
- **Decisions:** SUPPORTED, NOT SUPPORTED, INCONCLUSIVE, NOT TESTABLE (a precondition failed; the
  precondition is named) or PENDING (the input does not exist).

### 3.2 Hypotheses

| Id | Hypothesis | Rule | If not, we report … |
|---|---|---|---|
| **H1a** (primary) | `C` achieves positive useful lead on held-out participants at its budget-feasible operating point: macro of per-participant median `L_pred(C)` > 0. | SUPPORTED iff CI low > 0. NOT SUPPORTED iff CI high ≤ 0. Else INCONCLUSIVE. NOT TESTABLE if the offline lock records no feasible validation point for `C`. | … that the temporal model gives no positive useful lead at an acceptable FP budget on held-out participants, so the latency motivation is not supported offline. |
| **H1b** | `C` leads `A`: macro paired `L_pred(C) − L_pred(A)` > 0. | As H1a, on the paired difference. `A`'s lead is ≤ 0 by construction, so H1b adds little beyond H1a; it is reported for completeness. | … that `C` gives no earlier commit than reactive detection. |
| **CB** (informative, two-sided) | `C` versus `B` at their frozen operating points: macro paired `L_pred(C) − L_pred(B)`. | C_LONGER iff CI low > 0. B_LONGER iff CI high < 0. Otherwise NO_MATERIAL_DIFFERENCE iff −δ_lead < CI low and CI high < δ_lead. Else INCONCLUSIVE. A C_LONGER interval inside (0, δ_lead), or a B_LONGER interval inside (−δ_lead, 0), is qualified as *not material*. | … B_LONGER or NO_MATERIAL_DIFFERENCE: learned trajectory prediction adds no lead over physics extrapolation at the same budget, and B suffices for anticipation. |
| **H2** | `C`'s pooled test FP/min at its operating point ≤ `B_FP`. | Pooled FP/min = Σ FP / Σ active minutes. SUPPORTED iff CI high ≤ `B_FP`. NOT SUPPORTED iff CI low > `B_FP`. Else INCONCLUSIVE. | … that the FP budget chosen on validation does not transfer to held-out participants, so FP control is not demonstrated. |
| **H3** | `C`'s macro `TE_pred` MAE ≤ `δ_TE`. | SUPPORTED iff CI high ≤ `δ_TE`. NOT SUPPORTED iff CI low > `δ_TE`. Else INCONCLUSIVE. | … that predicted impact times are not accurate enough for audio scheduling at the declared tolerance; lead without timing accuracy is not useful. |
| **H4** (live) | Externally measured action-to-sound latency of `C` is lower than that of `A` by more than the measurement uncertainty `U`: macro paired `lat_C(p) − lat_A(p)`, where `lat` is the per-participant median over valid strikes of the primary method. | SUPPORTED iff CI high < −`U`. NOT SUPPORTED iff CI low ≥ −`U`. Else INCONCLUSIVE. PENDING if no external method passed §8. | … that no effective-latency reduction is measurable within the method's resolution; the offline lead does not translate into earlier sound. |
| **H4-B** (live) | As H4 for `B` versus `A`. | As H4. | As H4, for `B`. |

### 3.3 Reporting alongside the hypotheses

- **CB context.** Reported beside CB, with CIs and without a decision: the paired differences
  `C − B` in FP/min, FN rate, `TE_pred` MAE and zone accuracy.
- **Matched FP.** "Matched FP" means both operating points were selected under the same FP budget
  on validation. The achieved test FP/min of both is reported. The curve-based comparison at equal
  achieved FP/min (F1) is secondary and descriptive.
- **Sound-before-impact fraction.** For `B` and `C`: the fraction of externally measured strikes
  with negative physical `TE_audio`. This is not a hypothesis. Early sound is discussed as a
  potential perceptual defect and is not assumed to be good (README §5.4; REQ-060c).
- **H3 bound.** `δ_TE = max(δ_audio, 2 · s_phys)`.
  - `δ_audio` is the owner's audio-timing tolerance, with its rationale.
  - `s_phys` is the robust spread (IQR / 1.349) of the Phase 07 acoustic offset
    `t_impact_phys − t_impact_est`, when that validation is MEASURED.
  - Otherwise `s_phys` is undefined, `δ_TE = δ_audio`, and H3 is interpreted against geometric
    ground truth only.
  - The factor 2 is a declared candidate: a bound tighter than the ground truth's own spread would
    be meaningless.

## 4. Matching, harness and processing delay (Experiment 1)

### 4.1 Primary matching (frozen harness)

- **Harness:** the Phase 09 harness `spacedrums.eval` (version and source hashes in the offline
  lock), unchanged.
- **Matching:** ADR-0023. A committed strike and a POSITIVE label are paired within each session and
  hand when `|t_commit − t_impact_est| ≤ W`. Matching is zone-blind (zone is scored as zone
  accuracy), greedy one-to-one, with the boundary included.
- **W:** `W = W_PRIMARY_S`, frozen by the ADR-0023 rule on validation folds.

Declared consequence of this rule:

- Every matched pair has `L_pred ∈ [−W, +W]`, so reported lead magnitudes are bounded by `W`.
- An anticipatory commit made more than `W` before the estimated impact counts as one false
  positive and leaves the impact as a false negative. Early commits are therefore penalised in
  FP / FN, even when the sound would have been scheduled at an accurate predicted impact time.

### 4.2 Pre-declared sensitivity S1 (README §10.1 reference time)

Committed strikes are paired by `t_ref`: `t_impact_pred` for anticipatory strikes, and the detected
`t_impact_est` for `A`. The same `W` and exclusion rules apply, and `L_pred = t_impact_est −
t_commit` is unchanged.

S1 is reported for H1a, H1b, CB, H2 and H3 next to the primary result and never replaces it.
Implementation (`spacedrums.live_eval.offline.reference_time_evaluation`):

- The frozen `evaluate_session` runs on rows whose matching time is `t_ref`.
- Lead is then recomputed from the original commit times.
- Segment admissibility and FP attribution of a strike therefore use `t_ref` in S1.

**Open Question (owner, before the offline lock):** should README §10.1 be the primary rule? That
would need an amendment of ADR-0023 and a new version of this document.

### 4.3 Processing delay `Δ_proc`

- **Primary:** fixed per-arm delay `Δ_proc(X)`, the accepted Phase 16 live capture-to-decision delay
  of arm `X`'s decision path. Each value carries its run id in the offline lock. If only one
  accepted value exists, it applies to every arm and the report says so.
- **Appendix:** `Δ_proc = 0`.
- Replay uses `DelayPolicy("fixed", Δ_proc(X))`.
- Missing primary values block the offline lock (`DELTA_PROC_LIVE_S` is `None` today).

### 4.4 Harness self-checks before the run (abort on any failure)

1. The harness known-answer tests (`tests/eval/`) and the Phase 18 tests (`tests/live_eval/`) pass
   on the evaluated commit.
2. **TEST-CAUSAL-1** (`docs/architecture/causality-tests.md` §2) runs on every evaluated arm with
   its exact config and model package:
   - on two SYNTHETIC kinematic fixture sessions, never on test data;
   - perturbation kinds GARBAGE, REMOVED and SHIFTED; the donor for SHIFTED is the other session;
   - cut frames: every 10th frame plus every frame with a candidate or a reset in the reference run.
     Where that set exceeds 40 per session, 40 evenly spaced cuts of it are used (a declared CPU
     cap);
   - pass criteria: bit-identical records for deterministic arms, and absolute tolerance `1e-6` on
     numeric fields for learned arms (with identical non-numeric fields). The wall-clock stamp
     `t_inference_done` is excluded;
   - the report states per kind how many perturbations changed an output after the cut, so a
     vacuous pass is visible.
3. The offline lock's source hashes equal the files on disk for `eval`, `live_eval`, `geometry`,
   `commit`, `prediction`, `models` and `features`.

## 5. Metrics and strata (Experiment 1)

**Metrics.** All from the frozen harness, per README §10:

- `L_pred`: median, IQR, p10 / p90, fraction > 0.
- FP: count, FP / |S|, and FP per active minute (ADR-0023 active time).
- FN rate.
- `TE_pred`: MAE, bias and distribution.
- Zone accuracy and zone confusion.
- Impact-position error.
- Intensity agreement at commit time: Pearson r and MAE from the harness; Spearman ρ recomputed from
  the matched pairs.
- Trajectory ADE / FDE for arms that emit trajectories (`B`, `C-GBDT-traj`, `C`), in ROI units and
  pixels. The target is the future **causal tracker** output on the prediction's own time grid,
  used only inside a contiguous VALID span without reset (Phase 08 target semantics:
  `docs/features/feature-schema-v1.md`, "Window and target semantics"). It is not the physical tip.

**Strata.** Every stratum is a property of labels or recording metadata, never of an arm's output.

- per participant; pooled;
- by segment type; by zone; by hand;
- by **speed tercile**: the inward crossing speed of the ground-truth impact (`intensity_proxy_gt`),
  with tercile edges computed once from the pooled test positives. FP/min has no speed and is
  reported as "n/a".
- by lighting id and distance mark, where a stratum has at least two levels.

**Inference latency.** Offline, the Phase 13/16 isolated batch-1 p50 / p95 / p99 measurements named
in the offline lock are quoted, not re-measured. Live, each arm's inference latency comes from the
Experiment 2 timing records.

## 6. Statistics

- **Unit:** the participant. Events, frames and seeds are never treated as independent people.
- **Confidence intervals:** 95 % percentile bootstrap over participants, 10,000 resamples with
  replacement, `numpy.random.default_rng(18)`.
- **Missing values:** participants with an undefined value (for example, no matched event) are left
  out of that metric, and the count is reported.
- **Small samples:**
  - P = 1: no CI; decision INCONCLUSIVE.
  - P ≤ 3: the percentile CI equals [min, max] of the participant values, so a decision reduces to
    "every participant meets the criterion". The report states this and treats the result as a
    per-participant consistency statement, not a population inference.
  - Rule P07-SPLIT-1 holds out 2 test participants for P = 8–11 and 3 for P = 12–19. At the
    project-discovery target of 10–12 participants, this reading applies to Experiment 1.
- **Pooled FP/min CI:** participants are resampled and the ratio of summed FP to summed active time
  is recomputed.
- **Multiplicity:**
  - Seven decisions: H1a, H1b, CB, H2, H3, H4, H4-B. H1a is primary.
  - CIs are unadjusted 95 % intervals, and this is stated.
  - No p-values and no significance language are used.
  - No metric, stratum or subgroup is promoted after results are seen.
- **Sample size:**
  - `P_test` is the size of the frozen test roster, stated in the offline lock. It is not chosen
    for power.
  - `P_live` is reported after the fact.
  - No power claim is made.
- **Models:** each arm names exactly one model package in the lock (the ship ADR's final fit). No
  seed selection or ensembling happens at test time, unless the locked package is itself the
  ensemble.

## 7. Exclusion rules (declared; applied before any arm result is computed)

### 7.1 Offline

1. **Ground truth:**
   - Only reviewed POSITIVE labels with qc_status ACCEPTED or ADJUSTED are ground truth; the
     harness enforces this.
   - AMBIGUOUS and EXCLUDED labels, and positives flagged `excluded`, are not ground truth.
   - Strikes inside their intervals, or within `W` of an ambiguous event, are withheld from FP
     counts (ADR-0023).
2. **Sessions:** only the sessions of the frozen `ds-v1.0` test roster are used, after the Phase 06
   / 07 unusable-recording policy. No session or participant is excluded on the basis of any arm's
   output.
3. **Participants without positives:** a participant with no eligible POSITIVE label contributes to
   FP/min only. Their lead, timing and zone metrics are undefined, and the count is reported.

### 7.2 Live

1. **Sessions:**
   - A session without signed consent is never analysed.
   - A session whose calibration is refused or stale is not recorded (the application refuses to
     start).
   - An aborted session contributes only its completed blocks.
2. **External sync failure.** The session's *external* latencies are excluded, while its
   software-stamped results are still reported, when either:
   - the external recording's sync residual RMS exceeds the method's validated tolerance (§8); or
   - fewer than 3 sync markers matched.
3. **Strike (M1):** excluded when zero or two-plus candidate pad onsets, or sound onsets, lie inside
   the pairing window, or when the strike falls outside every arm block. Counts are reported per
   arm.
4. **Attribution:** as-treated, by the committed strike's `arm` field (the arm that actually
   sounded). Fallback events (C → B) are listed per block. Post-fallback strikes count for the
   fallback arm.
5. **H4 pairing:** a participant enters the paired H4 analysis only with at least one valid strike
   in both arms.

## 8. External timing methods: acceptance rules (Task 18.3)

Each method is **Pending Benchmark** until its developer pilot passes these rules. The thresholds
are declared candidates. The owner may amend them only before the live lock.

**M1 — pad + microphone** (primary for H4). GO iff all three hold:

1. **Known-separation click validation**, on the microphone and position to be used: at least 30
   pre-rendered click pairs with known sample separation, played through the output device. The
   measured separation must have |bias| ≤ 1.0 ms and 95th-percentile |error| ≤ 2.0 ms.
2. **Developer pad pilot:** at least 30 pad strikes, of which at least 90 % yield an unambiguous
   (pad onset, sound onset) pair.
3. **Combined uncertainty** `U_M1 = sqrt(e95_click² + r_pad²) ≤ 5 ms`, where `r_pad` is the median
   10–90 % rise time of the pad transient. `r_pad` is a conservative bound on pad-onset
   localisation, used until a contact reference exists.

M1 measures the difference of two onsets in the same recording, so its latency does not depend on
the `t_mono` mapping. Sync to `t_mono` only attributes strikes to blocks.

**M2 — high-frame-rate video.** GO iff:

1. the measured frame period ≤ 5 ms (at least 200 delivered FPS, from the file's timestamps);
2. a flash or LED driven at 30 or more known `t_mono` times is detected in at least 95 % of events,
   with |bias| ≤ 1 frame period.

`U_M2` = frame period + |bias|. Impact and sound are each quantised to a frame.

**M3 — software stamps.** Always computed and always labelled **SOFTWARE ESTIMATE**.

- `t_audio_out_est` is used only with an accepted Phase 04 output-latency run.
- Without one, M3 reports `t_audio_scheduled` and the scheduled play time, labelled "DAC path
  excluded".
- M3 never decides H4.

**Primary method for H4:** M1 if GO; otherwise M2 if GO; otherwise H4 and H4-B are PENDING and no
effective-latency claim is made (README §5.4).

## 9. Live design (Experiment 2)

- **Participants:**
  - live participants with signed live-session consent
    ([`../ethics/consent-form-live-addendum.md`](../ethics/consent-form-live-addendum.md)), after
    the ethics Open Question is answered;
  - the developer pilot comes first;
  - overlap with dataset participants is allowed and recorded, because no model is trained on live
    data;
  - the count is reported after the fact; the recruitment target is an Open Question.
- **Blocking and order:**
  - The arm is a blocked within-participant factor.
  - Arm order follows the Williams design for three arms (six sequences balanced for position and
    first-order carry-over).
  - Sequence index = (live participant index − 1) mod 6, recorded in `LiveSessionMetadata`.
- **Block content** (identical for every arm; a subset of the Phase 06 protocol; durations are
  candidates):
  - single hits per zone;
  - alternating hands on one zone;
  - repeated hits at the medium cued tempo;
  - fake swings;
  - stop-before-impact.

  External-measurement blocks follow: PAD_MIC on the pad zone, one per arm, in the same order.
- **Shadow logging:** every frame runs all three arms; exactly one sounds.
- **Blinding:**
  - The participant view shows the zones and cues only: no arm label, trajectory, TTI or decision
    overlay.
  - All arms use identical samples.
  - The operator console shows the arm.
  - A model fallback message, if any, can reveal C; it is logged.
- **Calibration:**
  - The Phase 14 wizard runs before the blocks, and its hash is recorded.
  - For M1, the pad is placed so that the pad zone's impact surface coincides with the pad surface
    in the image, checked with test strikes before the blocks.
- **Quantities:**
  - per strike, externally measured action-to-sound latency per arm (`L_sys` for `A`, physical
    `TE_audio` for `B` / `C`);
  - live FP / FN on scripted negatives and live `L_pred`, from the harness on the recorded session
    with reviewed Phase 07 labels;
  - the README §5.3 software decomposition per arm;
  - live inference latency per arm.
- **Offline expectations:** live results are compared with the offline ones descriptively.
- **No re-tuning:** test-participant offline numbers are never re-tuned after live sessions. Both
  locks precede their experiments, and nothing is trained or tuned on live data.

## 10. Tables and figures

**Figures:**

- **F1 (primary figure):** median `L_pred` (ms) against FP per active minute on test participants.
  - One interpolation-free curve per arm, from the declared one-knob sweep around each frozen
    point: `τ_commit` ∈ {0.02, 0.05, 0.10, 0.15, 0.20} s for every anticipatory arm, and
    `p_commit` ∈ {0.3, 0.5, 0.7} for every arm whose frozen point gates on a strike probability
    (`p_commit` > 0).
  - `A` is a single point. The frozen points are marked, and `B_FP` is drawn as a vertical line.
  - The sweep is descriptive; no operating point is re-chosen from it.
- **F2:** per-participant paired lead differences (`C − B`, `C − A`) with the macro CI.
- **F3–F5:** `TE_pred` histogram, zone confusion and FP by segment type, per arm.
- **F6:** FN rate and lead by speed tercile.
- **F7** (live): action-to-sound latency distributions per arm (external method).
- **F8** (live): software decomposition per arm.

**Tables:**

| Table | Content |
|---|---|
| T1 | per-arm pooled metrics at primary `Δ_proc` |
| T2 | per-participant metrics per arm |
| T3 | hypothesis outcomes |
| T4 | paired differences with CIs |
| T5 | strata |
| T6 | trajectory and intensity |
| T7 | S1 sensitivity |
| T8 | `Δ_proc = 0` appendix |
| T9 | validation-fold results at the frozen points (from the lock; not re-run) |
| T10 | live latency and decomposition per arm |
| T11 | method validation (`U`) |

## 11. Neutrality, exploratory analyses and integrity

- **Neutrality.** Every template has rows for outcomes where `A` or `B` is preferable, and each
  hypothesis is reported as SUPPORTED / NOT SUPPORTED / INCONCLUSIVE / NOT TESTABLE / PENDING with
  its failure reading. No winner is assumed (README §9).
- **Exploratory analyses** are labelled EXPLORATORY. They include:
  - motion changes under anticipatory sound (stroke kinematics per arm: a genuine system
    phenomenon, observed and reported);
  - curve-based matched-FP comparisons;
  - anything not declared above.
- **Causality** (README §13): every arm consumes only observations with timestamp ≤ the current
  frame's `t_capture`. Labels enter only after replay, at matching.
- **Confirmatory run on participant data.** It requires all of the following:
  - a clean tree;
  - the verified hash of this document;
  - the archived offline lock;
  - an empty ledger for that lock;
  - passing self-checks (§4.4).

  The ledger entry is reserved before any test data is read and kept even if the run fails. A
  second execution for the same lock is refused.
- **Development rehearsals.** Rehearsals on the SYNTHETIC kinematic fixture use development
  constants. They check machinery only, are never evidence, and never enter a participant table.

## 12. Symbols supplied by the locks (all PENDING on 2026-09-27)

| Symbol | Lock field | Source | Status |
|---|---|---|---|
| Dataset, labels, split, test roster, `P_test` | `offline.dataset.*` | Phase 07 freeze | PENDING (`ds-v1.0` absent) |
| Harness version and source hashes | `offline.harness.*` | Phase 09 freeze (`HARNESS_VERSION` still `-development`) | PENDING |
| `W` | `offline.matching.w_primary_s` | ADR-0023 rule | PENDING (`W_PRIMARY_S` is `None`) |
| `Δ_proc(X)` | `offline.delay.primary_s` | Phase 16 policy | PENDING (`DELTA_PROC_LIVE_S` is `None`) |
| `B_FP`, FN ceiling | `offline.budgets.*` | ADR-0024 / ADR-0025, owner | PENDING |
| `δ_audio`, `s_phys`, `δ_TE` | `offline.budgets.*`, `offline.acoustic.*` | owner; Phase 07 Task 07.6 | PENDING |
| `δ_lead`, CPU p95 bound | `offline.budgets.*` | owner (Phase 10/11) | PENDING |
| Arms: settings, operating points, model packages | `offline.arms[]` | Phases 09–11, ADR-0027 / ADR-0030 | PENDING |
| `U` and M1/M2 GO/NO-GO | `live.methods.*` | Task 18.3 pilot | PENDING |
| Live config, model and arm mapping | `live.config.*`, `live.arms` | Phases 13 / 14 / 16 | PENDING |
