# HW-01 Realtek audio profile

**Phase:** 04 · **Status:** IMPLEMENTED engine / output-latency evidence **PENDING**\
**Date:** 2026-09-21 · **Hardware:** HW-01 · **Clock:** `perf_counter`

## Candidate runtime profile

| Field | Value | Label |
|---|---:|---|
| Backend | PortAudio via `sounddevice`; Windows WASAPI or WDM-KS | candidate; Pending Benchmark |
| Sample rate | 48,000 Hz | candidate |
| Buffer size | 128 frames | candidate only; not selected by valid output-latency evidence |
| Runtime samples | public-domain prerecorded Roland TR-505 WAV files | IMPLEMENTED; hashes in `assets/samples/recorded-manifest.json` |
| Output latency | no accepted value | **PENDING** |

PortAudio-reported latency values are device metadata, not measurements, and are not substituted
for `t_audio_out - t_audio_scheduled`.

## Measurement attempts

The script emits 35 deterministic click signatures per buffer size and keeps captured audio only in
memory. A result is accepted only when all clicks are detected and `p90 - p10 <= 0.020 s`. This
criterion is a detector-consistency guard, not an acceptable-latency threshold.

| Buffer | Method / run | Actual result | Verdict |
|---:|---|---|---|
| 64 | Stereo Mix, `20260921-1532-p04-audio-loop-b64` | 34/35 detections; spread 0.1114 s; 0 callback xruns | rejected / PENDING |
| 128 | Stereo Mix, `20260921-1532-p04-audio-loop-b128` | 35/35; spread 0.1068 s; 0 xruns | rejected / PENDING |
| 256 | Stereo Mix, `20260921-1533-p04-audio-loop-b256` | 35/35; spread 0.1058 s; 0 xruns | rejected / PENDING |
| 512 | Stereo Mix, `20260921-1533-p04-audio-loop-b512` | 35/35; spread 0.1159 s; 0 xruns | rejected / PENDING |
| 128 | Stereo Mix, `20260921-1528-p04-audio-b128` | 35/35; bimodal 0.0018 s (15 trials) / 0.1218 s (20 trials); spread 0.1200 s; 0 xruns | rejected; predates the consistency guard, so its trial file self-labels `MEASURED` and must not be read as such / PENDING |
| 128 | microphone, `20260921-1530-p04-audio-b128` | 11/35 detections; 0 xruns | rejected / PENDING |
| 128 | microphone, `20260921-1531-p04-audio-b128` | all windows returned a peak, but spread was about 0.14 s | rejected after consistency guard was added; never accepted |
| 128 | Stereo Mix diagnostic, `20260921-1537-p04-audio-loop-b128` | modal digital alignment 0.121979 s; tap point upstream/unknown; 0 xruns | MEASURED diagnostic only; **not** output latency |

The microphone attempts include microphone input latency and acoustic propagation and did not yield
a stable onset. Stereo Mix has no documented guarantee that its tap is after the DAC. Therefore none
of these runs establishes the required DAC-output time, and no buffer-size winner is selected.

## Machinery self-test and clock mapping

Runs `20260921-1532-p04-audio-synth-b64`, `...b128`, `...b256`, and `...b512` each recovered
the injected 0.017 s delay in all 35/35 trials with zero spread. This is **SYNTHETIC** test evidence
for the detector only, never audio-latency evidence.

Run `20260921-1537-p04-audio-loop-b128` recorded an actual device-clock regression residual RMS of
0.004300 s over 2,888 callback samples and 0 callback xruns. It was run on a dirty development tree;
a clean-tree repeat is required before promotion to gate-grade MEASURED evidence.

## Required follow-up

Use a known post-DAC electrical loopback cable or a synchronized external recorder/reference marker,
run at least 30 events for each candidate buffer size, then choose the smallest buffer meeting a
predeclared underrun criterion. Until then `AudioScheduler` must be constructed only with a real
profile value supplied by such a run; it has no fabricated production default.
