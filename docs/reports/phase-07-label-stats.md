# Phase 07 — Label Statistics

Counts are MEASURED from the labels listed, grouped by evidence class. **Groups are never summed:** SYNTHETIC, DEV CAPTURE, PILOT and PARTICIPANT counts are separate tables and separate claims (integrity I-4).

> **No participant labels exist.** Every table below is SYNTHETIC or DEV CAPTURE material: generated observations and a developer recording. None of it is evidence about participants, about class balance in a real dataset, or about label quality. The participant tables are **PENDING** (Phase 06 conditions C-06-1…C-06-4).

> **Review state.** No human has reviewed any label: every count is generator output with `qc_status = PENDING_REVIEW`, so the adjustment rate is reported as PENDING rather than as 0 (`docs/reports/phase-07-agreement.md`).

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
