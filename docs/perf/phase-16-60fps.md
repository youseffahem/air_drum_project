# Phase 16 native 60 FPS assessment

Status: **PENDING**. Date: 2026-09-26 (+03:00), HW-01.

The condition for a native 60 FPS pipeline attempt is not met. The integrated
DSHOW webcam delivered about 30 FPS in the Phase 02 capability checks, including
requests for 60 FPS. No external camera is available. See
[the camera profile](../camera-profile-hw01-integrated-webcam.md) and the machine-readable
assessment `experiments/phase-16/native-60fps.json`. The profile also preserves the
original evidence's clean/dirty limitations; advertised FPS is not delivery evidence.

The Phase 16 unattended checks deliver about 30 unique camera frames per second,
but the synthetic-trained Arm C enters its existing processing-budget fallback.
No model predictions occur in these idle checks. They cannot establish sustained
Arm C capacity or a 60 FPS result. Replay processing capacity is reported only as
compute throughput. No temporal interpolation, repeated-frame rate increase or
camera resampling was introduced. The rejected half-resolution experiment changes
spatial resolution only.

The pinned model was trained at `dt_step_s = 1/30`. The existing model package
and cadence checks reject an incompatible input rate. No 60 FPS model was trained
and no causal resampler was added in this phase.

## Conditions for a later attempt

1. An external camera must first demonstrate native 60 FPS with the Phase 02
   timing, exposure, duplicates and drop checks.
2. Supply an eligible model cadence under the Phase 13 rule, with an explicitly
   verified causal resampler or a separately trained Phase 19 model.
3. Profile representative strokes with Arm C active throughout, record unique-frame
   delivery, drops and inference activity, and rerun regression, parity and causality.

`fps_end_to_end.py` refuses replay/perturbed profiles and requires nonempty model
predictions, continuous Arm C, at least 95% of the target delivery rate and at most
1% drops. These are candidate diagnostic thresholds, not new accepted requirements.
REQ-023 stays PLANNED pending reviewer action; the shortfall is documented here.
