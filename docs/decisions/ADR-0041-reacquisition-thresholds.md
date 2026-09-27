# ADR-0041 — Re-acquisition thresholds `g_max_frames` / `age_max_s`

Status: **DECIDED by the project owner, 2026-09-27: `g_max_frames = 3` is kept and
`age_max_s = 0.5` confirmed.** Keeping 3 is an **explicit engineering deviation from the
pre-declared sweep rule, which selected `g_max_frames = 6`**. By the owner's instruction, the
Phase 17 campaign was **not** re-run at `g_max_frames = 6`. Development evidence only; participant
confirmation PENDING.
Date: 2026-09-27. Phase: 17 (Tasks 17.3 / 17.7; "Decisions That Must Be Experimentally
Validated"). Related: README §8, ADR-0016, ADR-0039, ADR-0040 (D3, D4).

## Context

README §8 sets two thresholds that have been candidates since Phase 03:
- `g_max_frames` (3): how many frames a lost hand is bridged in `DEGRADED` before it becomes
  `INVALID`;
- `age_max_s` (0.5 s): how long after the last `VALID` frame the state becomes `STALE`.

Phase 17 lists their final values as a decision to validate experimentally. With DEGRADED commits
off (ADR-0039), the thresholds decide:
- whether a short loss is **bridged** or **reset**. A bridged loss keeps the track, and a strike
  inside the gap can be committed late at re-acquisition. A reset loses the strike, and
  re-acquisition starts from an empty history.
- the time-gap reset threshold `(g_max + 1.5) / fps` (ADR-0040 D3).
- how long a stretch of low-confidence observations may continue the track before it is cut to
  `STALE`. From `STALE`, only a `VALID` observation re-acquires.

## Experiment

`scripts/reacquisition_experiment.py` swept `g_max_frames` ∈ {1, 2, 3, 4, 6} ×
`age_max_s` ∈ {0.25, 0.5, 1.0} s. Everything else followed `configs/prototype.candidate.yaml`
(commits in VALID only; frame-drop guard 3). Each case was one replay with arm A sounding and arm B
shadowing.
- **Evidence run:** `experiments/phase-17/20260927-0047-reacquisition-experiment/` (clean source
  audit). The final gate verification repeated it with identical results:
  `experiments/phase-17/20260927-0053-p17-gate-verification/20260927-0145-reacquisition-experiment/`.
- **Preview run:** `…/20260927-0038-reacquisition-experiment/` failed its audit (two unrelated
  scripts were edited while it ran; `ABORTED.md`). It is not evidence.

The evidence parts:

- **(a) SYNTHETIC injection, 643 cases per grid point.** The six Phase 17 grid sequences, first two
  strikes each, with these faults at the approach, the impact and during idle:
  - the hand lost for 1–15 frames;
  - confidence 0.45 for 3–36 frames, with the true tip or with 0.015-ROI Gaussian jitter (an
    assumption: a weak estimate is also inaccurate);
  - camera stalls of 2–6 frames.

  Fault-induced FP / FN against the unperturbed run, Phase 09 matcher, W = 50 ms.
- **(b) The SYNTHETIC P07 labelled session** (recorded observations through the live pipeline).
- **(c) The three developer captures** through real perception. No truth, so informational.
- **(d) Occluded fake-outs**, 216 placements. A fake-out is a stroke that stops 2 or 10 mm above
  the surface; it was occluded for 1, 3 or 6 frames, starting 8 frames before to 3 frames after the
  stop. A commit added over the unoccluded stroke is a fabricated strike.

**Declared rule** (in the script's docstring, written before the first run):
1. Consider only points with no invariant violation or crash.
2. Of those, keep only the points with the fewest fabricated strikes (injection + fake-outs, arms A
   and B).
3. The best point minimises the fault-induced FP + FN of (a).
4. Keep the current 3 / 0.5 unless it is not eligible, or the best point is at least 5 % better
   without worsening (b).

A preview of the declared design showed that the fake-out set (d) had no loss longer than the
largest grid `g_max`. A **post-hoc** sensitivity set was therefore added before the clean run and
labelled as such: 336 placements, losses of 1–15 frames ending 4 frames before to 3 frames after
the stop. It re-applies the same rule.

## Results (`age_max_s = 0.5`; 0 invariant violations and 0 crashes at every point)

| `g_max_frames` | FP + FN (a), A + B | A: FP (all mistimed) / FN | B: FN | Fabricated in (a) | Fake-out commits added (d), all arm B | Post-hoc fake-outs, arm B |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 587 | 0 / 351 | 236 | 0 | 4 | 13 |
| 2 | **571** | 2 / 333 | 236 | 0 | 4 | 12 |
| 3 (candidate) | 585 | 15 / 332 | 238 | 0 | 4 | 12 |
| 4 | 586 | 15 / 332 | 239 | 0 | 4 | 11 |
| 6 | 593 | 15 / 332 | 246 | 0 | **3** | **10** |

- **`age_max_s`.** FP + FN at 0.25 / 0.5 / 1.0 s is 591 / 585 / 586 at `g_max` 3, and 0.5 s is
  best at every `g_max`. The differences are all in B's FN. `age_max_s` changed no fabricated count,
  no P07 score and no developer-capture commit.
- **P07 (b).** At every point: A 32 matched / 0 FP / 0 FN; B 4 / 0 / 28.
- **Developer captures (c).** No commit was added or removed at any point; only the DEGRADED /
  INVALID split moved (exp-5 at 6: 97 DEGRADED / 12 INVALID hand-frames vs 81 / 28 at 3).
- **Re-acquisition (SYNTHETIC).** VALID on the first clean frame at every point; after an
  occlusion the rule arm predicts again after a median of 33 ms.

Where the differences come from:

- **2 vs 3.** At 3, a 3-frame loss or stall is bridged and arm A commits the strike inside it late,
  at re-acquisition: 13 mistimed commits (6 occlusion, 7 stall). At 2 the loss resets and the
  strike is lost. FP + FN counts a late strike twice (FP + FN) and a lost one once, so 2 scores 14
  lower (−2.4 %, below the 5 % margin).
- **6 vs 3.** At 6, 6-frame losses and 4–6-frame stalls are bridged instead of reset, and B misses
  8 more strikes. A is unchanged: the frame-drop guard (3) blocks commits after longer gaps.
- **Fabricated strikes.** They come only from arm B, only on fake-outs, and only when the occlusion
  ends while the stick is still moving. After a reset, B anticipates from a fresh two-frame history.
  - A longer bridge avoids some of these resets: one 6-frame placement in (d); 13 → 10 in the
    post-hoc set.
  - Losses longer than `g_max` fabricate as before: 9- and 15-frame losses give 2 each at every
    point.
  - B's anticipation commits on many fake-outs whatever the thresholds: 139 commits over
    ADR-0039's 432 placements, under either DEGRADED policy.

**Declared outcome:** only the `g_max = 6` points have the fewest fabricated strikes (3; the
candidate has 4), so the current values are not eligible. The rule selects **`g_max_frames = 6`,
`age_max_s = 0.5`**. The post-hoc sensitivity selects the same point.

## Decision (project owner, 2026-09-27)

- **`age_max_s = 0.5 s` is confirmed** on development evidence: best at every `g_max`, with no
  effect on fabrication, P07 or the developer captures. This follows the declared rule.
- **`g_max_frames = 3` is kept.** This is an **explicit engineering deviation from the
  pre-declared sweep rule**, which selected `g_max_frames = 6` (and the post-hoc sensitivity agreed).
  The agent proposed the deviation, and the owner decided it. The engineering reasons:
  1. The deciding difference is 1 (declared) or 2 (post-hoc) arm-B commits in 216 / 336 synthetic
     placements. They come from B's post-reset anticipation, which `g_max` does not remove, only
     postpones to longer losses. The count keeps falling up to the largest value tested (6), so the
     rule's choice is the edge of the grid, not an identified optimum. A larger grid would keep
     pushing the bridge longer.
  2. The change would raise the time-gap reset threshold (D3) from 150 ms to 250 ms. It would also
     undo the premise of the frame-drop guard decision (D4, guard = `g_max` = 3, chosen at 3).
     Every Phase 17 campaign number was measured at 3. The measured cost is +8 B FN (+1.4 % FP + FN).
  3. The mechanism is arm B's, and it can be fixed in arm B at every `g_max`: for example, no
     anticipatory commit until the history after a re-acquisition holds enough observed frames.
     That is a separate, pre-declared experiment for Phase 18, with the participant fake-out
     segments.

**What the deviation means for the evidence:**
- The declared rule's outcome and every sweep number above stay on record unchanged. Only the
  adopted value differs from the rule's selection.
- By the owner's instruction, the frame-drop guard experiment and the Phase 17 campaign were
  **not** re-run at `g_max_frames = 6`. The only evidence at 6 is the sweep itself.
- Every other Phase 17 result was measured at the adopted value, 3.

## Consequences

- No config or code change: `g_max_frames = 3` and `age_max_s = 0.5` were already the values in
  `configs/prototype.candidate.yaml` and `configs/live.arm-C.candidate.yaml`. README §8 values
  remain candidates until participant data confirms them (ds-v1.0; PENDING).
- ADR-0040 D3 (time-gap reset at `(g_max + 1.5) / fps` = 150 ms) and D4 (frame-drop guard 3) stand
  as decided at `g_max_frames = 3`.
- Reopening this decision needs new evidence, preferably participant sessions with occlusion and
  fake-out segments. The sweep script re-applies the declared rule unchanged and will keep reporting
  6 on the same inputs.
- The failure catalogue records B's post-reset anticipation on fake-outs as a residual risk (F19).
  The proposed fix (a post-re-acquisition warm-up for B) is a Phase 18 item.
