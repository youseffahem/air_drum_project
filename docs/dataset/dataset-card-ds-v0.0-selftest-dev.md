# Dataset card — `ds-v0.0-selftest-dev`

**Kind:** SELFTEST · **Label:** TEST / DEVELOPMENT ONLY - SYNTHETIC and/or DEV CAPTURE labels; never participant evidence

**Labels version:** `labels-v1.0` · **Raw source:** `PENDING` · **Manifest hash:** `sha256:a72b90ed9048d93a922f40db077baa668b3ff9ab8bc6ef14d45cab52765a934b`

## 1. Purpose and intended use

Training and evaluation data for causal temporal strike anticipation from a webcam (Space Drums, README section 1). Intended use: the Phase 08-19 feature, model and evaluation work of this project. **Not** intended as a general drumming or gesture benchmark, and not released (Phase 23 decides release; consent scope below).

## 2. Collection protocol

Recorded under the Phase 06 protocol (`docs/protocols/recording-protocol.md`): cued segments covering single hits, alternating and near-simultaneous strokes, tempo and rapid blocks, movement between zones, fake swings, stops before impact, occlusion, tracking interruption, and distance / lighting variation. Every session carries a `SessionMetadata` document with the camera, audio, config and git provenance, and a `verify.json` with the applied unusable-recording policy.

## 3. Participants (aggregate, pseudonymised)

**PENDING — no participant sessions exist.** No participant has been recorded (Phase 06 conditions C-06-1…C-06-4), so this dataset version contains no participant material and no participant count is reported.

## 4. Label definitions

See `docs/dataset/labeling-rules-v1.0.md` for the normative rules. In short: a POSITIVE label is the first outside-to-inside crossing of a zone's impact surface by the **reference** (offline-smoothed) tip trajectory with inward speed above `v_min`, timed by sub-frame interpolation; `intensity_proxy_gt` is the inward-normal velocity component at that instant (a proxy, never a force). Negatives cover no-strike motion, fake swings, stops before impact, movement between zones, upward/exit crossings and tracking loss. AMBIGUOUS labels stay in the dataset and are excluded from every metric numerator and denominator; EXCLUDED labels lie in quarantined segments.

## 5. Label counts

### DEV_CAPTURE — DEV CAPTURE (developer recording; never participant evidence)

Labels: **21** · sessions: 1 · participants: 1 · metric-eligible: 3 · with physical GT: 0

| Class | Count | Share |
|---|---:|---:|
| `AMBIGUOUS` | 8 | 0.381 |
| `EXCLUDED` | 10 | 0.476 |
| `NEG_TRACKING_LOSS` | 1 | 0.048 |
| `NEG_UPWARD_CROSSING` | 1 | 0.048 |
| `POSITIVE` | 1 | 0.048 |

| Zone | Count |
|---|---:|
| `crash_ride` | 2 |
| `hihat` | 1 |
| `snare` | 8 |
| `tom1` | 5 |

| Hand | Count |
|---|---:|
| `LEFT` | 15 |
| `RIGHT` | 6 |

| Segment type | Count |
|---|---:|
| `ALTERNATING_ONE_ZONE` | 2 |
| `NEAR_SIMULTANEOUS` | 1 |
| `RAPID` | 6 |
| `SINGLE_HITS` | 5 |
| `TEMPO` | 5 |
| `WARMUP` | 2 |

| Participant | Count |
|---|---:|
| `DEV` | 21 |

| `intensity_proxy_gt` (ROI-norm/s, positives) | n | min | p25 | median | p75 | max |
|---|---:|---:|---:|---:|---:|---:|
| distribution | 1 | 0.3271 | 0.3271 | 0.3271 | 0.3271 | 0.3271 |

Ambiguous fraction: 0.3810 · excluded fraction: 0.4762 · adjustment rate: PENDING (nothing reviewed) · reviewed fraction: 0.0000

### SYNTHETIC — SYNTHETIC (generated observations; never participant evidence)

Labels: **65** · sessions: 1 · participants: 1 · metric-eligible: 64 · with physical GT: 0

| Class | Count | Share |
|---|---:|---:|
| `AMBIGUOUS` | 1 | 0.015 |
| `NEG_BETWEEN_ZONES` | 4 | 0.062 |
| `NEG_FAKE_SWING` | 3 | 0.046 |
| `NEG_NO_STRIKE_MOTION` | 11 | 0.169 |
| `NEG_STOP_BEFORE_IMPACT` | 4 | 0.062 |
| `NEG_TRACKING_LOSS` | 3 | 0.046 |
| `NEG_UPWARD_CROSSING` | 7 | 0.108 |
| `POSITIVE` | 32 | 0.492 |

| Zone | Count |
|---|---:|
| `crash_ride` | 2 |
| `hihat` | 14 |
| `snare` | 20 |
| `tom1` | 11 |

| Hand | Count |
|---|---:|
| `LEFT` | 34 |
| `RIGHT` | 31 |

| Segment type | Count |
|---|---:|
| `ALTERNATING_ONE_ZONE` | 2 |
| `ALTERNATING_TWO_ZONES` | 3 |
| `DISTANCE_VARIATION` | 4 |
| `FAKE_SWING` | 2 |
| `LIGHTING_VARIATION` | 2 |
| `MOVE_BETWEEN_ZONES` | 3 |
| `NEAR_SIMULTANEOUS` | 3 |
| `OCCLUSION` | 3 |
| `PAD_MIC` | 3 |
| `RAPID` | 4 |
| `SINGLE_HITS` | 18 |
| `STOP_BEFORE_IMPACT` | 2 |
| `TEMPO` | 9 |
| `TRACKING_INTERRUPTION` | 3 |
| `WARMUP` | 4 |

| Participant | Count |
|---|---:|
| `SYNTHETIC` | 65 |

| `intensity_proxy_gt` (ROI-norm/s, positives) | n | min | p25 | median | p75 | max |
|---|---:|---:|---:|---:|---:|---:|
| distribution | 32 | 0.2062 | 1.2122 | 1.2122 | 1.2122 | 2.0618 |

Ambiguous fraction: 0.0154 · excluded fraction: 0.0000 · adjustment rate: PENDING (nothing reviewed) · reviewed fraction: 0.0000


## 6. Splits

**PENDING — no split is frozen for this dataset version.** The split rule (ADR-0021, `P07-SPLIT-1`) is fixed as a function of the participant count `P` so the numbers cannot be chosen after seeing a result.

## 7. Quality control and agreement

**PENDING / NOT VALIDATED — no annotation pass has been performed.** The QC protocol (`P07-QC-1`) and the review tool exist and are tested; no human annotator has reviewed any label, and no inter-annotator agreement is claimed.

## 8. Physical ground truth (pad + microphone)

**PENDING — no microphone track paired for this session (Task 07.6).** Ground truth in this dataset version is **geometric only** (ADR-0002 fallback).

## 9. Known limitations

- Ground truth is **geometric**: `t_impact_est` is the crossing of a virtual impact surface by the estimated stick tip, not a physical impact. Where the pad + microphone condition exists, `t_impact_phys` gives the measured offset for those strikes only (ADR-0002).
- Single camera, no depth: the tip position is 2-D in ROI-normalized coordinates (ADR-0005); motion towards or away from the camera is not observed.
- Labels are **non-causal** by construction: they come from a trajectory smoothed over the whole recording. They are valid as evaluation references and as training targets, and must never be used as model inputs (docs/architecture/causality-tests.md section 1.1).
- Negative classes are threshold-based (`rules.Thresholds`); the thresholds are candidates until a review pass on real recordings refines them.
- The reference smoother may round off sharp reversals at impact; the error near impacts is quantified against manual tip annotations, which needs recordings.
- Zones, not articulations: rim / centre / edge are out of scope (REQ-015).

## 10. Licence, consent scope and reuse

- **Consent scope:** PENDING - no consent record exists (Phase 06 C-06-4)
- **Licence:** proprietary graduation-project material; no release is made by Phase 07 (`What Must NOT Be Done Yet`). A release decision belongs to Phase 23 and is bounded by what each participant consented to.
- **Reuse conditions (Q49):** reuse requires the consent scope to permit it, the labelling rules document and this card to travel with the data, and any derived result to state the labels version and the split file it used.

## 11. Versioning and change log

Versioning rule: **any** change to the rules, thresholds, tracker or smoother produces a new `labels_version`; **any** change to the accepted sessions produces a new `ds` minor version. The `labels_hash` in every label record makes a stale version detectable rather than merely discouraged.

- ds-v0.0-selftest-dev — initial manifest (2026-09-22).
