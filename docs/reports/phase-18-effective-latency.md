# Phase 18 — Effective-latency analysis (Task 18.6)

**Status: PENDING. No effective-latency number exists, and none is claimed.**

- No external timing method has passed its declared acceptance rules (pre-registration §8;
  [`phase-18-external-methods.md`](phase-18-external-methods.md)).
- No live session with a person has been recorded ([`phase-18-live-results.md`](phase-18-live-results.md)).
- Following README §5.4, reduction of effective latency is therefore **not claimable**, and H4 and
  H4-B are PENDING.

## 1. What will be measured, and how (declared)

| Quantity | Definition | Source | Label when it exists |
|---|---|---|---|
| `L_sys` (physical), arm A | sound onset − pad onset for arm-A strikes, in one microphone recording | M1 | MEASURED (external) |
| `TE_audio` (physical), arms B / C | sound onset − pad onset for B / C strikes; negative = sound before the physical impact | M1 | MEASURED (external) |
| Paired difference `lat_C − lat_A` (and B − A) | per participant: difference of median latencies; macro mean with its participant-bootstrap CI | `analyze_live.py` → H4 / H4-B | MEASURED |
| Sound-before-impact fraction, B / C | fraction of valid strikes with negative physical `TE_audio` | M1 | MEASURED |
| Software estimate | `t_out − t_impact_est`, with `t_out` the scheduled play time (DAC path excluded) until Phase 04 accepts an output latency | M3 | SOFTWARE ESTIMATE, never a measurement |

The latency of M1 is a difference of two onsets in the same recording, so neither the microphone
path nor the `t_mono` mapping enters it. The mapping (drum sounds aligned with the software audio
events) only attributes each strike to the arm that sounded, as-treated.

## 2. The conceptual relation is not a measurement

README §5.4 writes effective latency as `L_eff ≈ max(0, L_sys − L_pred)`. That relation motivates
the research question and nothing more. Phase 18 does not substitute it for a measurement:

- an offline `L_pred` does not become a latency number;
- a software-stamped `t_audio_scheduled` does not become `t_audio_out`.

When M1 data exists, the report compares the measured `lat_C − lat_A` with `−median L_pred(C)`
from the live harness. That comparison is descriptive and shows how far the conceptual relation
holds on this system.

## 3. Interpretation rules (declared before any data)

- **H4 SUPPORTED:** the whole 95 % interval of `lat_C − lat_A` lies below `−U`. `U` is the validated
  method's uncertainty (for M1, `sqrt(e95_click² + r_pad²)`).
- **Sound before the physical impact** is reported, not celebrated. A negative `TE_audio` means the
  drum sounds before the stick lands. Whether players perceive this as "on time", "early" or
  "wrong" is not assumed. The optional questionnaire reports it descriptively, and REQ-060c
  forbids claiming that sound is guaranteed before impact.
- **Few participants:** with P ≤ 3 the interval spans the participant values, and the reading is
  per participant (pre-registration §6).

## 4. What exists today (2026-09-27)

- M1 analysis chain: exercised end to end on a SYNTHETIC live session with a SYNTHETIC microphone
  track of known latencies (see the live-results report). Machinery only.
- M1 part (i), the known-separation click check, **failed** on HW-01's built-in microphone array
  (runs `20260927-1228` / `-1230-methods-m1-clicks`: 0 of 40 pairs detected, twice; no click train
  recoverable). M1 is therefore NO_GO with that microphone
  (`20260927-1232-methods-decide`), and an external microphone is required before the pad pilot.
- M3: implemented, but on the development captures it applies only to live-camera sessions with
  a single clock. The DAC path stays excluded while the Phase 04 output latency is PENDING.
