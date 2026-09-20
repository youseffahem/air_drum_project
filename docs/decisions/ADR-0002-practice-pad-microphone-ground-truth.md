# ADR-0002 — Optional practice-pad + microphone physical-impact ground truth

| Field | Value |
|---|---|
| Status | **Accepted** (owner decision recorded during roadmap definition; formalised in Phase 00, Task 00.9) |
| Date | 2026-09-20 (recorded) |
| Deciders | Project owner |
| Related | `phases/README.md` §5.2 (`t_impact_phys`, `t_acoustic_onset`), §6; Phases 06, 07, 18; REQ-005, REQ-039, REQ-050c, REQ-060c; consent form items B1, C3b |

## Context

The system's reference impact time is `t_impact_est`: the sub-frame interpolated crossing of the *tracked* tip through a virtual zone's impact surface (README §5.2). This is derived from the same vision pipeline that is being evaluated, so tracking error and interpolation error contaminate the reference. In air drumming there is no physical impact at all, so no independent ground truth exists in the primary use case. Q60 forbids claiming "sound before physical impact" without measurement, and REQ-050c asks for a scientifically defensible evaluation.

## Decision

Add an **optional recording condition** in which the participant strikes a real **practice pad** placed so that the pad surface coincides with a virtual zone's impact surface, while a **microphone** near the pad records the tap. The acoustic onset gives `t_impact_phys` (README §5.2), an external ground truth for a subset of strikes. The condition is:

- **Optional** for participants (consent form B1) and for the project: if no pad/microphone is available, Phases 06–07 proceed without it and all `t_impact_phys`-based results are reported as **Pending**.
- Used to (a) validate `t_impact_est` against physical impact time (Phase 07 QC), (b) provide `t_impact_phys` for a subset of Phase 18 timing measurements, (c) calibrate the audio-out timing chain together with `t_acoustic_onset` of the drum sound if both are captured on one audio track.
- **Never assumed**: the existence of `t_impact_phys` is per-recording metadata; any metric using it states the number of strikes it covers.

## Alternatives considered

| Alternative | Why not |
|---|---|
| No physical ground truth; `t_impact_est` only | Cheapest, but leaves the validity of the reference time itself untested; weakens REQ-050c. Remains the **default** for all non-pad recordings. |
| Contact sensor / piezo on the pad | More precise onset than a microphone, but adds electronics and a sync problem; ESP32/IMU-style hardware is out of scope by spirit (REQ-201–203 apply to the sticks, but the same simplicity argument holds). Could be revisited by ADR if the microphone proves too noisy. |
| High-speed reference camera | Expensive; another sync problem; not available (`hardware-inventory.md`). |
| Marker-based reference tracking as "ground truth" | Measures the same modality (vision) with a different estimator — useful as a **benchmark condition** (REQ-211) but not an independent physical ground truth. |

## Consequences

- Phase 06 protocol gains pad segments; Phase 01 `SessionMetadata`/`FrameSample` contracts gain an audio track and an `has_phys_gt` flag; Phase 07 defines the acoustic-onset labelling rule and its uncertainty.
- Audio–video clock alignment becomes a measured quantity (Phase 06/07): the microphone track must be mapped onto `t_mono` with documented residual uncertainty, or the condition yields no usable `t_impact_phys`.
- Consent and information sheet cover microphone audio (done: IS-v0.1 §4, CF-v0.1 B1/C3b).
- Equipment is **Open Question** in `hardware-inventory.md` (pad, microphone).
- Results split into "with physical GT (n strikes)" and "geometric reference only"; the thesis must present both and never merge them silently.
