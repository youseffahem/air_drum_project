# Phase 18 — External timing methods: pilot and validation (Task 18.3)

**Status: no method is GO.**

| Method | Decision | Why |
|---|---|---|
| **M1** (pad + microphone) | **NO_GO** with HW-01's built-in microphone array; **Pending Benchmark** with an external microphone | Part (i), the known-separation click check, failed on the built-in array; the developer pad pilot (part ii) needs a person, a pad and a microphone at the pad |
| **M2** (high-frame-rate video) | **Pending Benchmark**; used only if M1 fails its declared pilot (decision E1) | no ≥ 200 FPS camera or LED reference in the inventory |
| **M3** (software stamps) | **ESTIMATE ONLY**, by definition | the Phase 04 output latency is still PENDING, so the DAC path is excluded |

- Acceptance rules: pre-registration §8, declared before any pilot data.
- Decision record: `experiments/phase-18/20260927-1232-methods-decide/result.json`
  (`scripts/external_methods_pilot.py --decide`).
- Machinery: `spacedrums.live_eval.{acoustic, video, sync, software}`, `scripts/external_methods_pilot.py`.
- Hardware: HW-01. Executor: Claude Opus 5.5 via Claude Code, recorded in each run's `execution.json`.
- All runs are on a dirty tree (Phase 18 uncommitted), so they are development evidence.

## 1. SYNTHETIC machinery self-test

Run `experiments/phase-18/20260927-1228-methods-selftest/`. Known answers throughout; this measures
nothing physical.

| Check | Construction | Recovered |
|---|---|---|
| Click-pair validation | 12 pre-rendered pairs (20–200 ms) under a common 87.3 ms delay | 12 / 12 pairs; bias 1.6e-11 s; e95 3.6e-9 s |
| Pad + speaker pairing (M1 core) | 7 strikes, latencies −30 … +140 ms, two with sound *before* the pad | 7 / 7 paired; max error 1.0e-7 s; both early sounds recovered |
| Event-train sync | 10 markers, offset 4987.66 s, drift 8e-5, two spurious events | offset 4987.66 s, drift 8.0e-5, residual RMS 4.6e-12 s |
| Flash detection (M2) | 10 flashes at 240 FPS | 10 / 10, error 0 (frame-quantised) |

The first self-test run (`20260927-1227-methods-selftest`, kept with `SUPERSEDED.md`) printed a
wrongly computed *reference* offset: the fit was right, the script's expected value was not. It is
fixed and was re-run.

## 2. M1 part (i): known-separation click check on HW-01 (MEASURED developer pilot, no person)

**Set-up:**

- `external_methods_pilot.py --m1-clicks --allow-audio-device`, with the default devices:
  - input: "Microphone Array (Realtek Audio)";
  - output: "Speakers / Headphones (Realtek Audio)";
  - host API: MME.
- 48 kHz; 40 click pairs at separations 20 / 50 / 100 / 150 / 200 ms; click gain 0.3.
- One duplex stream: the output latency and input latency are common to both clicks, so they
  cancel.
- The room audio stayed in memory; only ±15 ms excerpts around located clicks are stored: none in
  the first run, one in the second (`click-excerpts.npz`).

| Run | Clicks located (NCC ≥ 0.3) | Pairs detected | Declared outcome |
|---|---:|---:|---|
| `20260927-1228-methods-m1-clicks` | 0 | 0 / 40 | **FAIL** (needs ≥ 30 pairs, \|bias\| ≤ 1 ms, e95 ≤ 2 ms) |
| `20260927-1230-methods-m1-clicks` | 1 | 0 / 40 | **FAIL** (reproduced) |

**EXPLORATORY post-hoc diagnostic (second run; it does not change the declared outcome):**

- **Alignment failed.** The whole-stimulus envelope cross-correlation found no click train in the
  recording (peak 0.023, estimated delay −0.75 s, which is impossible). The per-click statistics
  printed in that run's `result.json` were measured at arbitrary times and are invalid, as its
  `NOTE.md` says. The script now refuses to report them when the alignment fails.
- **The diagnostic itself is sound.** On a SYNTHETIC band-limited path (800–4000 Hz, delay
  93.1 ms), template correlation falls to 0.21 and the declared validator finds nothing, while the
  diagnostic re-aligns (peak 0.99) and the envelope onsets recover all pairs
  (`tests/scripts/test_phase18_scripts.py`).
- **Reading.** On HW-01's built-in microphone array, the played clicks are not recoverable as a
  click train at all. This agrees with the rejected Phase 04 microphone attempts (11/35 detections;
  0.14 s spread).
- **Cause not identified.** Candidates:
  - the array's built-in processing (noise suppression, acoustic echo cancellation);
  - a low system output volume;
  - speaker / microphone placement.

**Consequence.** M1 needs an **external microphone without processing**, placed near the pad and
the speaker, and then a new part (i) run before the pad pilot.

**Owner decision E1 (2026-09-27).** M1 is equipped and evaluated as the primary timing method. The
§8 thresholds and the declared estimator stay unchanged, and M2 is used only if M1 fails its
declared pilot.

## 3. What remains (person / equipment)

| Step | Needs | Command |
|---|---|---|
| M1 part (i) with an external microphone | a microphone without DSP, placed at the pad | `external_methods_pilot.py --m1-clicks --allow-audio-device --input-device <mic>` |
| M1 part (ii): developer pad pilot, ≥ 30 pad strikes on the pad zone | practice pad; microphone; developer | `run_live_session.py --live --kind DEV_CAPTURE --pad-zone <zone> --mic-device <mic> ...`, then `external_methods_pilot.py --m1-pad --session <dir> --recording <dir>/audio_track.wav` |
| M1 decision | parts (i) and (ii) | `external_methods_pilot.py --decide --click <result.json> --pad <result.json>` |
| M2 pilot, only if M1 fails (decision E1): ≥ 30 LED / flash events at known `t_mono`, ≥ 200 FPS, with an independent bias reference | phone camera; LED driven by the audio output (hardware) | `external_sync.py --method M2 ...` and `video.m2_validation` |
| Phase 04 output latency (M3's DAC term) | post-DAC loopback cable or external recorder | Phase 04 procedure (`docs/audio-profile-hw01-realtek.md`) |
