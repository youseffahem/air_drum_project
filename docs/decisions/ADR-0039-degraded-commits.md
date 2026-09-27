# ADR-0039 — DEGRADED commits stay disabled

Status: DECIDED on development evidence (default unchanged: commits in VALID only); participant
confirmation PENDING. Date: 2026-09-26. Phase: 17 (Task 17.7). Related: README §8, ADR-0016,
ADR-0018, ADR-0040.

## Context

README §8 allows commits in `DEGRADED` "only if explicitly enabled and experimentally validated
(Phase 05/17) — default No"; Phases 01 and 05 left it as an Open Question. `DEGRADED` covers two
different situations: an **observed** tip with confidence in `[c_min, c_valid)`, and a **bridged**
frame (no usable observation; the filter extrapolates existing state for at most `g_max_frames`).
Q34–Q35: never fabricate a strike during tracking loss.

## Experiment (paired; only `commit.allow_degraded_commits` differs)

`scripts/degraded_experiment.py`, run `experiments/phase-17/20260926-2250-degraded-experiment/`
(2026-09-26, HW-01, dirty tree, development evidence). Decision rule declared in the script before
the first P1 run: *P1 may become the default only if it lowers FN **and** adds no fabricated FP
(fake-outs included) for every arm.* Policies: P0 = VALID only (current), P1 = VALID + DEGRADED.

| Evidence | Arm | P0 | P1 |
|---|---|---|---|
| (a) Phase 09 harness, SYNTHETIC P07 session (32 positives, 37.7 s; only 9 DEGRADED frames) | A | 32 matched, 0 FP, 0 FN | identical |
| | B | 4 matched, 0 FP, 28 FN | identical |
| (b) SYNTHETIC injected occlusion (2, 3, 6 frames) and low confidence (3, 9 frames) at approach / impact / idle; 375 strikes per arm | A | 347 matched, 28 FN, 0 fabricated, 5 mistimed | **361 matched, 14 FN**, 0 fabricated, 5 mistimed |
| | B | 78 matched, 297 FN, 0 / 0 | identical |
| | C-GRU (development model) | 6 matched, 81 fabricated, 136 mistimed | 6 matched, **84 fabricated**, 138 mistimed |
| (c) SYNTHETIC **fake-outs**: a stroke stopping 2–20 mm above the surface (no strike exists), occluded 1–3 frames from 8 frames before to 3 after the stop, 3 speeds × 4 heights; 432 placements per arm | A | **0** commits | **45 fabricated strikes** (2–5 per speed/height configuration, all 12 affected) |
| | B | 139 (anticipation's inherent fake-out FP) | 139 (unchanged) |
| (d) developer captures through real perception (no ground truth) | A, exp-5 (81 DEGRADED frames) | 2 commits | 4 (+2, unverifiable) |
| | B, exp-5 / A and B, exp-6 | 0 | 0 |

Invariant violations: 0 in every run of both policies (I1 is evaluated against the policy's own
allowed set). Arm A's whole FN reduction comes from **low-confidence observed** frames at the
impact; every fabricated strike comes from **bridged** frames, where the filter's extrapolation
crosses the surface that the real stick never reached.

## Decision

**Keep `commit.allow_degraded_commits = false`** (P0) for every arm and for Phase 18. P1 fails the
declared rule twice: arm A fabricates 45 strikes on occluded fake-outs, and the development C-GRU
adds 3. The measured cost of the decision is arm A's 14 extra FNs (3.7 % of the injected strikes),
all in low-confidence-at-impact cases.

Recorded option, **not evaluated and not adopted**: commits on *observed* DEGRADED frames only
(never on bridged frames) would keep A's FN gain without the fabrication mechanism, but
`TrackState` does not distinguish the two cases; it would need a contract change and its own
experiment (Phase 18 or later, with participant data).

## Consequences

- No config or code change; README §8 stays as written ("default No").
- Phase 18 must not enable DEGRADED commits without a participant experiment that includes
  fake-out segments (Phase 06 `FAKE_SWING` / `STOP_BEFORE_IMPACT` with occlusion).
- The confirmation on participant data is PENDING (no dataset exists).
