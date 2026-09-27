# Phase 18 — Limitations and threats to validity (Task 18.8)

**Status:** threats register COMPLETE for the design; the result-dependent entries stay PENDING
until the confirmatory run and the live sessions exist. No number in this document is a result.
Every quantity below is declared, a candidate, a development observation with its run id, or
PENDING.

## 1. What Phase 18 has not shown (2026-09-27)

| Claim the thesis might want | Status | Why |
|---|---|---|
| C gives positive useful lead on held-out participants (H1a) | **PENDING** | `ds-v1.0` does not exist; the offline confirmatory run has not happened |
| C versus B at the same FP budget (CB) | **PENDING** | as above; operating points and budgets are not set (ADR-0024 / ADR-0025) |
| FP budget holds on held-out participants (H2) | **PENDING** | as above |
| Predicted-impact timing is accurate enough (H3) | **PENDING** | as above; the tolerance `δ_audio` is an owner value, and the acoustic spread `s_phys` is not measured |
| Anticipation reduces **effective** action-to-sound latency (H4) | **PENDING, no claim** | no external timing method has passed its acceptance rules; no live session with a person exists |
| Sound arrives before the physical impact | **no claim** (REQ-060c) | never measured; the sound-before-impact fraction exists only as a declared statistic |

## 2. Threats to validity

| # | Threat | Direction / consequence | Mitigation in the design | Residual |
|---|---|---|---|---|
| T1 | **Participant count.** Rule P07-SPLIT-1 holds out 2 participants for P = 8–11 and 3 for P = 12–19. | For P ≤ 3 the bootstrap interval equals [min, max] of the participant values; population inference is impossible. | Declared (pre-registration §6): decisions then read "every held-out participant meets the criterion"; per-participant tables are always shown. | Strong. The owner kept P07-SPLIT-1 and the planned 10–12 participants (decision D1, 2026-09-27), so 2–3 are held out. |
| T2 | **Matching reference (ADR-0023 vs README §10.1).** The frozen harness pairs on `t_commit`. | Matched `L_pred` ∈ [−W, +W]; commits earlier than `W` become FP + FN. Lead magnitudes are therefore capped by `W`, and early anticipation is penalised. This also applies to every Phase 10–12 development lead. | S1 (§10.1 reference time) is pre-declared beside the primary; the owner kept ADR-0023 primary (decision A1, 2026-09-27). | Lead is interpretable only up to `W`; S1 is reported beside it. |
| T3 | **Geometric ground truth.** `t_impact_est` is the crossing of a virtual surface by the estimated tip, not a physical event. | Timing errors are relative to a reference with its own error; the geometric–physical offset is unmeasured (Phase 07 Task 07.6 PENDING). | H3's bound uses `max(δ_audio, 2 s_phys)` when `s_phys` is measured; otherwise H3 is interpreted against geometric truth only. | Physical interpretation of `TE_pred` is not available. |
| T4 | **Tracker noise in targets.** Trajectory ADE / FDE targets are the future causal tracker output (Phase 08 target semantics). | Errors mix prediction error and tracking noise; a model can be "wrong" against noise. | Stated with every trajectory table (T6). | Trajectory error is not physical tip error. |
| T5 | **Single camera and single laptop (HW-01).** No 60 FPS mode is delivered (Phase 02); CPU latency is specific to HW-01. | Results do not generalise to other hardware; frame quantisation (~33 ms at 30 FPS) dominates `L_sys`. | Hardware id on every run; no generalisation claimed. | A second machine (HW-02) is not inventoried. |
| T6 | **Processing delay `Δ_proc`.** The live capture-to-decision delay is PENDING (Phase 16); a ~52 ms replay compute proxy exists but is not accepted. | Replay leads shrink by `Δ_proc`; the wrong constant biases every lead. | Primary = the accepted per-arm value (lock); the zero-delay appendix is shown; locks refuse a missing value. | Needs representative live strokes. |
| T7 | **Layout generalisation.** Models are trained on one zone template; calibrated layouts are "untested departures" (ADR-0037). | Moved zones may change performance. | Calibration hash recorded per live session; the offline test uses the dataset layout. | No claim beyond the recorded layouts. |
| T8 | **Cued behaviour vs natural play.** Segments are cued (single hits, alternating, tempo, fake swings). | Natural drumming (fills, dynamics, ghost notes) is not represented; FP attribution follows the cue's segment type. | Strata by segment type are reported; free play is optional (Open Question). | Results describe cued playing only. |
| T9 | **Anticipatory sound may change motion.** Hearing early sound may alter the stroke. | Live `L_pred` / FP differ from offline; a genuine system effect, not an artefact. | Exploratory motion summary per sounding arm (`analyze_live.py`); blinding. | Exploratory only. |
| T10 | **External-measurement uncertainty.** M1 needs pad-onset localisation (conservative `r_pad`); M2 is frame-quantised; M3 excludes the DAC path while the Phase 04 output latency is PENDING. | H4 can be INCONCLUSIVE even with a real effect, since `U` enters the rule. | Declared GO thresholds; H4 PENDING without a GO method; M3 never decides H4. | Only the click part of M1 was piloted in Phase 18, and it failed on the built-in microphone (T11). |
| T11 | **Built-in microphone.** HW-01's array may apply DSP (noise suppression, echo cancellation) to speaker sound. | M1 onsets could be distorted or cancelled. | The click-pair pilot measures the recording path at the chosen position. | **Measured:** part (i) failed twice (0 / 40 pairs; no click train recoverable), so M1 is NO_GO on the built-in array and an external microphone is required (external-methods report). |
| T18 | **Live arm B inherits the model's horizon.** `DecisionPipeline` builds B from the model config's `anticipator` block (ADR-0036), so with the development model (K = 1) live B extrapolates 33 ms ahead instead of its locked K. | Experiment 2 would compare C with a handicapped B (2 / 30 strikes committed in the rehearsal). All live arms also share one `commit` block, so B and C cannot each run at their own locked commit settings. | Found by the Phase 18 live rehearsal and code review; recorded as a precondition of the live lock. | ADR-0036 amended by the owner (2026-09-27): live B at the offline-locked settings with per-arm commit settings. Implementation and re-verification PENDING before any live session. |
| T19 | **One-frame arm-switch lag.** A block's first frame is decided by the previous arm. | A few strikes at block boundaries sound with the previous arm. | As-treated attribution by the commit's `arm`; switch frames recorded per block. | Negligible if attribution is as-treated; stated. |
| T20 | **Frozen-geometry boundary edge case.** A tip sample exactly on the impact surface (within 1e-9 of the ellipse boundary) opens an entry episode without a candidate in `GeometryEngine.observe`, so the strike is missed. | Practically impossible on continuously filtered positions; deterministic on grid-aligned SYNTHETIC tracks. Labels and arms use the same geometry. | Reported; Phase 18 test tracks avoid exact boundary values. | Frozen Phase 04 code unchanged; owner to decide whether to fix in a later phase. |
| T21 | **One model fallback removes C for the whole session.** The sticky fallback (ADR-0036) fires on inference p95 above 10 ms or total processing p95 above 33.3 ms over the last 30 model frames, on a capture-cadence mismatch, or on a model exception. It also fires while C runs in shadow; no recovery mode exists, and later switches to C are refused. | A participant can end with no C blocks, which lowers the paired C sample. It happened once in two SYNTHETIC live rehearsals on HW-01 (the repeat inside the final verification). | As-treated attribution; fallbacks are listed per block; a participant without C data leaves the paired C analysis by rule (pre-registration §7.2, item 5). | Owner decision C1 (2026-09-27): the fallback is kept and the loss accepted. Affected participants leave the paired C analysis by rule, and the losses are reported. |
| T12 | **Developer involvement.** The developer wrote the system, ran the pilots and will run the sessions. | Operator expectations can leak into cues and pacing. | Pre-registration, blinding of the participant, fixed Williams orders, scripted cues, a second-person reproduction (Task 18.9). | The operator is not blinded. |
| T13 | **Synthetic-trained development model.** The only live C package is a SYNTHETIC-trained GRU (ADR-0036); no shipped participant model exists. | Every development C result is meaningless for the research question. | All such runs are labelled SYNTHETIC / development; the locks require the shipped model. | Until ADR-0030 is decided. |
| T14 | **Multiplicity.** Seven decisions and many strata. | Some interval will exclude its threshold by chance. | H1a is primary; CIs are unadjusted and stated as such; strata are descriptive; no post-hoc promotion. | Readers must weigh H1a first. |
| T15 | **Lighting / distance / background.** Recorded per session (REQ-027 / REQ-028) but not varied systematically in the live protocol. | Robustness is shown only across what the dataset contains. | Strata by lighting / distance when ≥ 2 levels exist. | Limited to the recorded conditions. |
| T16 | **Marker condition.** None used (REQ-009, REQ-211). | — | Any future marker result must be labelled fallback / benchmark. | N/A today. |
| T17 | **Ethics.** The approval question is unanswered (Phase 00). | No participant or pilot-volunteer session may be recorded. | The live runner refuses PILOT / PARTICIPANT without signed consent; the consent addendum is a draft. | Blocks Experiment 2 entirely. |

## 3. Known failure modes of the machinery (from development runs)

- A cold or slow model call can trip the live budget and fall back to B (Phase 16 / 17). The live
  analysis attributes as-treated and shows the fallback per block. C then stays disabled for the
  rest of the session (T21).
- Replayed sessions carry mixed clocks (original `t_capture`, replay-time processing stamps).
  M3 rejects such records instead of reporting nonsense.
- `detect_onsets` thresholds are relative to the loudest frame. M1 therefore detects pad onsets
  per PAD window, after the located sounds are subtracted, so that louder drum samples elsewhere do
  not mask pad taps.
