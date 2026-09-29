# Live FPS on HW-01 (T2)

**Status: FAIL WITH EVIDENCE** (owner decision, 2026-09-28 +03:00).

All values are development measurements on HW-01 (i7-7820HQ, CPU only, integrated webcam DSHOW
640×480 YUY2, 30 FPS requested) on an uncommitted tree: HEAD `d8d29a7` plus the T1 live-mirror and
T2 changes. They are not MEASURED gate or thesis evidence under the reproducibility policy. Evidence
(git-ignored, local, sha256 manifest): `experiments/pre-participant/20260928-t2-live-fps/`.

## Question and outcome

With the owner in frame, the live app delivered fewer than 30 FPS and dropped frames. T2 tested
whether the display path caused this. It did not. With no window at all, the app reaches 27.81–28.11
FPS with 7.34–8.50 % dropped frames. **The current HW-01 ceiling is limited by the hand/stick
recognition + decision computation.** No display thread was implemented, and no further T2 source
changes will be made.

## Changes kept in the working tree

The owner kept these because they gave a measured improvement over the old implementation (below):

- `ui/preview.py` `mirror_preview`: `cv2.flip(frame, 1)` replaces `frame[:, ::-1].copy()`. The pixels
  are identical, verified by tests, and every camera-orientation render stays byte-identical.
- `cv2.pollKey()` replaces `cv2.waitKey(1)` in the four per-frame window loops: `app/main.py`,
  `app/calibrate.py`, `scripts/show_guide.py` and `scripts/exposure_blur_check.py`. The one-shot
  `waitKey(1)` after destroying windows is unchanged, and so is `scripts/measure_capture_latency.py`,
  whose protocol defines its `waitKey(1)`.
- Test stubs follow `pollKey` (`tests/ui/test_live_preview.py`), `scripts/profile_pipeline.py` stubs
  it in headless profiles, and `ui/README.md` notes the measured key-call cost.

## How the display path was suspected

The T1 mirror check (live, no recording, no audio) delivered 26.47 FPS (app summary). 1,057 frames
were delivered and 179 were dropped. Recognition + decision took 26.9 / 46.6 ms (median / slow 5%).
Phase 16 profiling stubs out `imshow` and `waitKey`, so the display tail had never been measured.
Camera-free benchmarks then showed `waitKey(1)` at 11.9 ms (median) in a tight loop and 3.4 ms with 27
ms of simulated work between frames. They also showed the slice-copy mirror at 1.4–1.7 ms. **These
benchmarks overstated the live cost:** in the live runs below, `waitKey(1)` took 1.94–2.03 ms and
`pollKey()` 0.38–0.44 ms (median per frame).

## Pre-declared tests

Both rules were written and hashed before any of their runs. The thresholds are those of
`scripts/fps_end_to_end.py` (0.95 × 30 FPS, at most 1 % drops) without its model-arm clauses; the
prototype runs arm A.

| Test | Pre-declaration sha256[:16] | Runs (60 s each, owner in frame playing across the four zones) | PASS iff |
|---|---|---|---|
| old/new | `9a4fdb13f6768097` | old-1, new-1, old-2, new-2 | both **new** runs: ≥ 28.5 FPS on both measures and drops/delivered ≤ 1 % |
| no-window ceiling | `2446293933bbb608` | ceiling-1, ceiling-2 | both runs: the same rule |

The **new** runs use the working tree. The **old** runs use the same code with `waitKey(1)` and the
slice copy restored at runtime; nothing else differs. The **ceiling** runs use the working tree with
`--no-window`, so no render, `imshow` or key call happens in the loop. All runs used the live source,
the prototype config, no recording, no audio and one OpenCV thread. The windowed runs used the
experiment overlay.

FPS is measured two ways. *Whole run* is delivered frames over the capture-timestamp span of the run.
*App summary* is the app's `fps_measured`, which covers at most the last 900 delivered frames.

## Results

| Run | Captured s | FPS whole run | FPS app summary | Dropped | Dropped / delivered | Recognition + decision median / slow 5% ms | Key call median ms |
|---|---:|---:|---:|---:|---:|---|---:|
| old-1 | 59.5 | 26.24 | 27.00 | 233 | 14.93 % | 27.4 / 44.9 | 2.03 |
| new-1 | 50.7 | 28.88 | 29.11 | 66 | 4.51 % | 27.9 / 41.3 | 0.44 |
| old-2 | 26.8 | 25.10 | 25.10 | 136 | 20.21 % | 29.6 / 46.9 | 1.94 |
| new-2 | 59.6 | 27.63 | 26.90 | 152 | 9.22 % | 29.4 / 43.8 | 0.38 |
| ceiling-1 | 59.6 | 27.81 | 28.71 | 141 | 8.50 % | 36.0 / 49.8 | — |
| ceiling-2 | 59.6 | 28.11 | 28.14 | 123 | 7.34 % | 34.8 / 49.9 | — |

- **old/new: FAIL.** new-1 meets the FPS bound but drops 4.51 %. new-2 misses both bounds (27.63 /
  26.90 FPS, 9.22 %).
- **Ceiling: FAIL.** ceiling-1 is at 27.81 FPS for the whole run and drops 8.50 %. ceiling-2 is at
  28.11 / 28.14 FPS and drops 7.34 %.
- **Measured improvement, new vs old** (pairs in run order): +2.64 and +2.53 FPS (whole run); drops
  14.93 → 4.51 % and 20.21 → 9.22 %.
- old-2 and new-1 ended before 60 s without an error event, which is consistent with a q press. The
  cause was not established. The playing workload was not controlled: the number of committed
  strikes per run was 6–23 (arm A).
- The ceiling runs had higher recognition + decision times than the windowed runs. **The cause was
  not established** and is not attributed.

## Conclusion

The display path is not the limiting factor. With no window, the app delivers 27.81–28.11 FPS with
7.34–8.50 % dropped frames, in the same range as the windowed new build. Recognition + decision
alone took 34.8–36.0 ms (median) and 49.8–49.9 ms (slow 5%) in the ceiling runs, against 33.3 ms per
frame at 30 FPS. The Phase 16 options for reducing it (half-resolution hands, IMAGE mode, a perception
thread or process) were screened and rejected there (`docs/perf/phase-16-perf-log.md`).

## Scope limits

- Tested conditions only: prototype config (exposure −6), no recording, no audio, one person, one
  session. Room lighting was not recorded for these runs.
- The pre-participant developer session of the same morning
  (`experiments/pre-participant/20260928-developer-session/`) ran slower: 10.4–16.0 FPS, with
  recognition + decision medians of 42.6–51.8 ms. It used an exposure −5 config copy, and some runs
  were in record mode. T2 did not re-measure those conditions, and the difference is not attributed.
