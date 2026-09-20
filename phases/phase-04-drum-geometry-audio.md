# Phase 04 — Virtual Drum Geometry & Audio Engine

## Status

Planned

## Purpose

Implement the fixed virtual drum-zone registry (MVP: Snare, Hi-Hat, Tom 1, Crash/Ride; V1: ~7 zones), the **impact geometry** (impact surfaces with inward normals, valid downward/inward entry test, first-entry-per-episode rule, **sub-frame crossing-time interpolation**, impact position), the trajectory–zone intersection routine that works identically on observed and predicted trajectories, and the local-sample **audio engine** with time-targeted scheduling, polyphony, intensity-proxy-to-gain mapping, and a measured audio output latency. No strike commit logic yet (Phase 05).

## Why This Phase Exists

The strike definition (Q36–39) is geometric and deterministic. Keeping it in a separate module — rather than inside a learned model — is the trajectory-first decision (Q42): the model predicts motion; geometry decides impact; this gives explainability and lets Baselines A, B, and C share one impact definition. Audio output latency is a term of `L_sys` (README §5.3) that only a real audio engine can measure.

## Relationship to Research Contribution

- Provides `t_impact_est` (sub-frame) — the reference time for **every** timing metric in Phases 09–19.
- Provides the deterministic mapping `TrajectoryPrediction → StrikeCandidate` used by rule-based and learned anticipators alike.
- Provides the measured audio output latency, without which `L_sys` and `TE_audio` cannot be reported.

## Inputs

- Phase 01 contracts (`TrajectoryPrediction`, `StrikeCandidate`, `CommittedStrike`, `AudioEvent`, zone config schema, `Geometry` and `AudioScheduler` interfaces).
- README §6 event taxonomy, §7 coordinate convention.
- ADR-0003 (MVP zone set).
- Local drum samples (royalty-free or self-recorded; licence recorded).

## Expected Outputs

- `geometry` module: zone registry, shapes, impact surfaces, intersection, sub-frame crossing, episode tracking.
- `audio` module: sample bank, scheduler, mixer, device-clock mapping, latency measurement script.
- Zone layout config (MVP 4 + V1 candidates) with all positions marked *candidate* until Phase 05 playtesting / Phase 14 calibration.
- Audio output latency measurement (MEASURED) on the development hardware.
- Geometry unit-test suite on synthetic trajectories.

## Dependencies

- Phase 01 Exit Gate. (Independent of Phases 02–03; may run in parallel.)

## System Components

- `src/spacedrums/geometry/` — `zones.py` (registry, shapes), `impact.py` (surfaces, entry test, crossing interpolation, episodes), `intersect.py` (trajectory → candidates), `layouts/` (MVP/V1 layout configs).
- `src/spacedrums/audio/` — `bank.py`, `scheduler.py`, `mixer.py`, `device.py` (clock mapping), `gain.py` (intensity proxy → gain).
- `scripts/measure_audio_latency.py`.
- `assets/samples/` (with `LICENSES.md`).

## Architecture

### Zone model

```
Zone {
  zone_id, name, trigger_type: HAND_TIP (enum open; FOOT reserved, not implemented),
  shape: Ellipse(center, rx, ry, angle) | Polygon(points)      # ROI-normalized
  impact_surface: Segment(p0, p1) | Arc(...)                    # subset of the boundary
  inward_normal: unit vector pointing into the zone from the surface
  allowed_hands: [LEFT, RIGHT]  (default both; reserved for experiments)
  sample_id, gain_curve_id
}
```

- MVP layout (candidate positions in ROI-normalized coordinates, to be tuned in Phase 05): Hi-Hat upper-left, Snare lower-centre-left, Tom 1 upper-centre, Crash/Ride upper-right. V1 adds Tom 2 (upper-centre-right), Floor Tom (lower-right), 7th zone Open Question (Ride split from Crash, or second cymbal).
- "Downward/inward" (Q37): for drum-like zones the impact surface is the **upper** boundary and the inward normal points toward +y (downward in the image); for cymbal-like zones the surface may be tilted; the normal is stored explicitly so no zone hard-codes "down".

### Impact geometry

- **Entry test:** given consecutive tip positions `p_{i-1}` (outside) and `p_i` (inside), the segment `p_{i-1}→p_i` intersects the impact surface, and the crossing velocity `v = (p_i − p_{i-1}) / Δt` satisfies `v · n_in ≥ v_min` (tunable). Crossings that enter through a non-impact part of the boundary, or with `v · n_in < v_min`, are **zone entries but not strikes**.
- **Sub-frame crossing time (Q39):** `t_cross = t_{i-1} + s·Δt`, where `s ∈ [0,1]` is the segment parameter at the surface intersection (linear interpolation; a quadratic option using filtered acceleration is a candidate for benchmarking). `t_impact_est = t_cross`.
- **Impact position (Q38):** the intersection point on the surface, stored with the candidate.
- **Episode rule:** an entry episode begins at the first valid entry and ends when the tip leaves the zone (or tracking becomes `INVALID`); at most one strike per episode. Re-entry after leaving starts a new episode (refractory is Phase 05's concern).
- **Same routine for predicted trajectories:** `intersect(trajectory, source)` accepts any ordered list of `(t, p)`; for `TrajectoryPrediction` the list is `(t_ref + k·dt_step, p̂_k)`; the first valid entry yields a `StrikeCandidate` with `t_impact_pred` and `TTI`.

### Audio engine

```
CommittedStrike ──► scheduler: t_target_play → device-time; enqueue AudioEvent (lock-free)
audio callback (fixed buffer size B, sample rate F): mix events whose target falls within the buffer at the exact sample offset; apply gain
device clock ◄─► t_mono mapping (measured offset/drift)
```

- Sample-accurate placement within the buffer (offset = `(t_target − t_buffer_start) · F`), so that timing error is not quantized to whole buffers.
- Polyphony: multiple simultaneous events per buffer (near-simultaneous hits, Q12).
- Intensity proxy → gain: monotone mapping (candidate: clipped linear or power law between tunable proxy bounds); labelled as proxy mapping, not force.
- If `t_target_play` is already in the past (reactive or late), play at the earliest sample and record the lateness in `TimingRecord`.

## Detailed Tasks

### Task 04.1 — Zone Registry and Layout Configs
- **What:** Implement `Zone`, registry load/validate from config, MVP and V1 layout files, hand-agnostic default, open `trigger_type` enum.
- **Why:** Q16–Q18, Q55 (kick extensibility), Q11.
- **Depends on:** Phase 01 config schema.
- **Evidence:** Schema validation tests; rendering of the layout on a blank ROI (screenshot).

### Task 04.2 — Shapes and Impact Surfaces
- **What:** Ellipse and polygon containment tests; surface representation (segment/arc) with explicit inward normal; validation that the surface lies on the zone boundary.
- **Why:** Q36–37.
- **Depends on:** 04.1.
- **Evidence:** Unit tests (points inside/outside, normal direction, surface-on-boundary check).

### Task 04.3 — Segment–Surface Intersection and Sub-Frame Crossing
- **What:** Robust segment–segment and segment–arc intersection; parameter `s`; `t_cross`; degenerate cases (grazing, starting on the surface, both points inside). Optional quadratic interpolation using filtered acceleration (candidate; benchmarked in Phase 07 against offline labels).
- **Why:** Q39 — sub-frame impact time; nearest-frame timing is explicitly rejected.
- **Depends on:** 04.2.
- **Evidence:** Unit tests with analytic ground truth on synthetic trajectories (known crossing times); numerical error reported.

### Task 04.4 — Valid-Entry Test and Episode Tracking
- **What:** Implement `v · n_in ≥ v_min`, first-entry-per-episode, episode start/end, and the rejection of upward/random crossings; produce `StrikeCandidate` for observed trajectories (`source = REACTIVE`, `t_impact_est` set).
- **Why:** Q36–37; duplicate suppression at the geometry level (per episode) complements Phase 05's refractory logic.
- **Depends on:** 04.3.
- **Evidence:** Unit tests: downward entry → candidate; upward crossing → no candidate; hovering inside → one candidate only; leave-and-re-enter → new episode.

### Task 04.5 — Trajectory Intersection for Predicted Trajectories
- **What:** `intersect(trajectory, source)` generic over `(t, p)` lists; for predictions return the first valid entry with `t_impact_pred`, `TTI = t_impact_pred − t_ref`, impact position, crossing velocity (from predicted step), and `source ∈ {RULE, MODEL}`. Handle predictions that start inside a zone (no candidate unless the trajectory exits and re-enters).
- **Why:** Trajectory-first: this is the single deterministic bridge from predicted motion to predicted strike, shared by Baseline B and all models.
- **Depends on:** 04.4.
- **Evidence:** Unit tests with synthetic predicted trajectories; equivalence test: feeding an observed trajectory as if predicted yields the same crossing time as the reactive path.

### Task 04.6 — Sample Bank and Licences
- **What:** Load WAV samples per zone (one or more velocity layers optional), resample to the engine rate, record licences.
- **Why:** Q53 — local recorded samples.
- **Depends on:** None.
- **Evidence:** `LICENSES.md`; load tests.

### Task 04.7 — Audio Device, Clock Mapping, and Callback Mixer
- **What:** Open the output device with a configurable buffer size `B` and sample rate `F`; map device stream time to `t_mono` (offset + drift estimate); implement the callback mixer with sample-accurate event placement, polyphony, and late-event handling; expose xrun/underrun counters.
- **Why:** README §5.1/§5.3; Q12 near-simultaneous hits.
- **Depends on:** 04.6.
- **Evidence:** Unit tests with a fake device clock; integration test producing a click at a target time and verifying sample offset in a captured output buffer (loopback where available).

### Task 04.8 — Scheduling API
- **What:** `AudioScheduler.schedule(committed) -> AudioEvent` computing `t_target_play = committed.t_impact_target`, `t_audio_out_est = t_target_play` if in the future else `now + measured_output_latency`; record `t_audio_scheduled`.
- **Why:** Anticipatory commits schedule sound *at* the predicted impact time; reactive commits play as soon as possible.
- **Depends on:** 04.7.
- **Evidence:** Unit tests for future/past targets; `TimingRecord` fields populated.

### Task 04.9 — Audio Output Latency Measurement
- **What:** Measure `t_audio_out − t_audio_scheduled` for events scheduled "now": candidate method = play a click while recording the output with a microphone (or loopback cable/virtual device) synchronized to `t_mono` via a known reference (e.g. the same recorder capturing a second, software-timed marker), repeat ≥ 30 times per buffer size (candidate), report median/p90 per `B`. Document method limitations (microphone path latency).
- **Why:** README §5.3 — the audio output term of `L_sys`.
- **Depends on:** 04.7.
- **Evidence:** Experiment-log JSON per buffer size; MEASURED table in the audio profile; chosen `B` recorded with rationale (latency vs. underruns).

### Task 04.10 — Intensity Proxy → Gain Mapping
- **What:** Configurable monotone mapping with tunable bounds; document that the proxy is kinematic (Q14).
- **Why:** Q14.
- **Depends on:** 04.8.
- **Evidence:** Unit tests (monotonicity, clipping).

### Task 04.11 — Layout Rendering
- **What:** Draw zones, impact surfaces, normals, and (later) impact points on the ROI view; clear geometric style (Q20).
- **Why:** Q20 — geometry clarity before realism.
- **Depends on:** 04.1.
- **Evidence:** Screenshot; overlay cost measured (should be negligible; measured anyway).

## Data Requirements

- Synthetic trajectories for tests (generated by test code; not data).
- Drum samples with licences.
- Developer audio recordings for the latency measurement (not dataset).

## Algorithms / Technical Approach

- Containment: ellipse implicit equation with rotation; polygon ray casting.
- Segment–segment intersection with parameter `s`; segment–arc via quadratic solve with angular range check.
- Sub-frame time: linear interpolation (primary); quadratic candidate.
- Entry validity: dot product with inward normal against `v_min`.
- Audio: callback mixer; per-event sample offset; gain from proxy mapping; device clock mapping by linear regression over stream time samples.

## Interfaces / Contracts

- Implements `Geometry.intersect` and `AudioScheduler.schedule` (Phase 01).
- Produces `StrikeCandidate` (REACTIVE for observed; RULE/MODEL when called by anticipators) and `AudioEvent`.
- Exposes `AudioStats { underruns, events_late, output_latency_measured }` for the debug overlay and session metadata.

## Tests

- **Unit:** all geometry cases listed in Tasks 04.2–04.5; mixer placement; scheduler future/past; gain mapping.
- **Property tests:** random trajectories — crossing time monotone in `s`; no candidate without a surface crossing; at most one candidate per episode.
- **Integration:** synthetic trajectory → candidate → schedule → audible click (manual check) and `TimingRecord` completeness.
- **Causality note:** geometry on observed trajectories uses only `p_{i-1}, p_i` (past/current); the routine never looks ahead.

## Measurements

| Quantity | Method | Label |
|----------|--------|-------|
| Crossing-time numerical error on synthetic trajectories | Task 04.3 tests | MEASURED |
| Audio output latency per buffer size (median, p90) | Task 04.9 | MEASURED |
| Underrun rate per buffer size | Task 04.9 | MEASURED |
| Device-clock mapping residual | Task 04.7 | MEASURED |
| Geometry + scheduling compute time per frame | profiling | MEASURED |

## Experimental Design

- Audio latency: factor = buffer size (candidate set spanning small to safe); ≥ 30 clicks per level; response = output latency distribution and underruns; choose the smallest `B` with acceptable underruns (acceptability threshold To Be Experimentally Determined and recorded).
- Interpolation comparison (linear vs. quadratic) deferred to Phase 07 where dense offline reference crossings exist.

## Acceptance Criteria

1. Zone registry loads MVP and V1 layouts; kick-compatible enum present; hand-agnostic default.
2. Geometry tests pass, including upward-crossing rejection and one-strike-per-episode.
3. Sub-frame crossing time implemented and tested against analytic ground truth.
4. Predicted-trajectory intersection yields `t_impact_pred`/`TTI` and matches the reactive path on identical input.
5. Audio engine plays scheduled samples with sample-accurate placement; polyphony works; late events handled.
6. Audio output latency measured and documented per buffer size; chosen `B` justified.

## Definition of Done

- Implementation, tests, measurements, audio profile document, layout screenshots, gate record PASS; integrity checklist applied.

## Risks

- Windows audio stack may impose high minimum latency with some backends → benchmark backends (Pending Benchmark), document.
- Ellipse/segment intersection numerical edge cases → property tests.
- Sample licences → verified before use.

## Failure Modes

- Grazing trajectories produce flickering entries → episode rule + `v_min` gate; log borderline cases.
- Audio underruns at small `B` → measured; choose `B` on evidence; expose counters.

## Fallback Strategy

- If callback-based audio is unavailable/unstable, use a blocking-stream backend with larger buffers and document the increased latency term.
- If quadratic interpolation is unstable, keep linear (primary).

## Artifacts Produced

- `src/spacedrums/geometry/`, `src/spacedrums/audio/`
- `configs/zones/mvp4.candidate.yaml`, `configs/zones/v1-7.candidate.yaml`
- `assets/samples/` + `LICENSES.md`
- `scripts/measure_audio_latency.py`, `docs/audio-profile-<device>.md`
- `experiments/phase-04/*.json`
- `docs/gates/phase-04-gate.md`

## Exit Gate

Reviewer verifies geometry tests and audio latency measurement. PASS → Phase 05 may start once Phase 03 has also passed.

## What Must NOT Be Done Yet

- No commit logic, refractory, or duplicate suppression across episodes (Phase 05).
- No anticipation/extrapolation.
- No MIDI output (not core; future feature at most).
- No realistic drum-kit visuals.
- No kick zone implementation (enum reserved only).

## Open Questions

- 7th V1 zone identity (Ride split vs. second cymbal) — Open Question for the owner.
- Are tilted impact surfaces for cymbal-like zones needed in V1, or is an upper boundary sufficient? (Phase 05 playtest)
- Which audio backend on Windows gives the lowest reliable output latency? (Pending Benchmark)

## Decisions That Must Be Experimentally Validated

- `v_min` (minimum inward crossing speed) — Phase 05/07.
- Zone positions/sizes — Phase 05 playtest, Phase 14 calibration.
- Buffer size `B` — Task 04.9.
- Linear vs. quadratic sub-frame interpolation — Phase 07.
- Intensity proxy definition and gain mapping — Phase 07/11.
