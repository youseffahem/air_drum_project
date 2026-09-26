# Phase 13 — In-loop inference and software timing

Status: PENDING live timing and gate-eligible measurements; development replay diagnostics.
Hardware: HW-01, Intel i7-7820HQ, Windows Python 3.11, TorchScript CPU, one intra-op thread.
Date: 2026-09-26 (+03:00). Actual Codex model and effort: UNVERIFIED.

The runs use uncommitted Phase 13 changes (`git_dirty: true`). Their recorded durations
are development diagnostics, not MEASURED gate evidence under the reproducibility
policy. The raw report labels identify the collection method; they do not override
the clean-commit requirement.

## What was executable

`scripts/live_latency.py` runs the production application, records raw frames and all
streams, and requests A active/B+C shadow followed by C active/A+B shadow. It measures
adapter duration in the loop per hand and per-strike software stamps. In live mode it
reports capture→available→tracking→features→inference→candidate→commit→audio-scheduled
terms where present, plus capture-to-commit. Shadow audio terms are null. Audio output,
acoustic onset and physical impact remain unmeasured.

The user confirmed that no developer with sticks was available. Live stroke timing,
Arm-C-vs-baseline live frame drops, playability and an accepted live delay constant
remain PENDING. Recorded replay drops are original capture drops; they cannot measure
the effect of enabling C in a live session.

## Final development runs

Final stable-source evidence is under
`experiments/phase-13/20260926-0928-p13-gate-verification/`:

- `candidate-budget/live-timing.json`: candidate inference budget 10 ms **for both
  hands combined per frame**, total budget 1/30 s, sliding window 30 frames. Values
  are candidates derived from the 30 Hz requested mode and earlier isolated model
  costs; Phase 16 must validate them. Startup is included.
- `comparison-no-fallback/live-timing.json`: the explicit parity config disables
  fallback for a replay-only same-session A/C comparison. This is not approval to
  disable fallback in live use.
- `faults/faults.json`: controlled-clock SYNTHETIC traces of missing model, missing
  statistics, hash mismatch, slow model, total processing delay and unavailable B.

Both runs replayed 171 frames of `swing-L2-exp-5`. The following values are
development diagnostics in milliseconds, including startup. Inference rows include
per-hand adapter calls that emitted a prediction; the budget monitor includes all
adapter calls and sums both hands per frame.

| Run / active arm | Prediction calls | C inference p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| Candidate budget / A | 37 | 1.288 | 5.921 | 55.761 |
| Fallback disabled / A | 116 | 1.230 | 1.947 | 12.794 |
| Fallback disabled / C-GRU | 145 | 1.182 | 1.822 | 2.113 |

| Run | Full-frame processing p50 ms | p95 ms | max ms |
|---|---:|---:|---:|
| Candidate budget | 39.605 | 60.581 | 109.079 |
| Fallback disabled | 36.986 | 51.243 | 158.813 |

The candidate-budget run disabled shadow C at frame 29: `inference p95 exceeds configured budget`.
Its recorded window inference p95 was 12.285 ms; the processing
monitor's final p95 was 82.840 ms. A remained active. The requested
switch after frame 84 was refused, so this run did not complete a C-active block.

The fallback-disabled replay switched after frame 84 and completed the C-active
block. One original capture drop occurred in the A-active block and zero in the
C-active block; these historical drops cannot establish the live cost of C. Both
replays leave `software_decomposition` empty to avoid mixing clock epochs. The
recorded strike streams include A/C stamps; no B strikes occurred in this session.
Live per-strike A/B/C comparison and delay reconciliation remain PENDING.

### Controlled fault traces

| SYNTHETIC fault | Fallback target | Commits in two-frame trace | Result |
|---|---|---:|---|
| missing_model | B | 0 | PASS |
| missing_stats | B | 0 | PASS |
| wrong_hash | B | 0 | PASS |
| slow_model | B | 0 | PASS |
| total_processing | B | 0 | PASS |
| B_unavailable | A | 0 | PASS |

All six cases passed. Separate integration tests cover switching during nonempty
trajectories and verify that shadow model strikes never reach the audio scheduler.

## Delay reconciliation

The parity harness uses each frame's measured perception/decision processing plus
its original capture-to-available interval. No fixed Phase 09 delay policy constant
was changed: replay processing is not evidence of live capture behavior. Proposed
materiality rule for the eventual live session is a p95 shift of at least 1 ms or
any changed commit set; either requires rerunning the affected offline comparisons.
This remains a candidate engineering rule, not a frozen participant protocol.

## Reproduce and complete

From the repository root, with the pinned development package present:

```powershell
.venv/Scripts/python.exe scripts/live_latency.py --config configs/live.arm-C.candidate.yaml --source live --output experiments/phase-13/live-developer --max-frames 600 --switch-frame 300
```

This records a developer session, uses the software scheduler without opening the
audio output device, and never supplies acoustic/effective latency. A developer with
sticks must be present. A fallback may prevent the requested C block; that is an
observed failure to complete the comparison, not permission to claim it completed.
The eventual shipped model and accepted budgets require a new pinned config and run.
