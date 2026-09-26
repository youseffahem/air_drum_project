# Phase 14 — Calibration repeatability, wizard duration and validation strikes

| Field | Value |
|---|---|
| Status | **PENDING for every MEASURED quantity of the phase.** `L_prior` repeatability, wizard duration and per-zone Arm A validation detections need a person following the wizard at the camera; no developer live calibration exists (owner action, §4). The analysis and all machinery are IMPLEMENTED and exercised on SYNTHETIC and replayed developer inputs (§2, §3), which are labelled as such and are not the phase measurements. |
| Submitter | Claude Code agent (Claude Opus 5.5, `claude-opus-5-5`; reasoning effort: max), acting for the project owner, 2026-09-26 |
| Evidence run | `experiments/phase-14/20260926-1047-p14-gate-verification/` (HEAD `a8ea862…`, **dirty** tree: Phase 14 changes uncommitted; diagnostics only until the clean rerun) |
| Method | `scripts/calibration_repeatability.py` over repeated calibration files of one subject/setup (same camera profile hash, ROI, template and fit mode) |

## 1. Quantities and method

| Quantity (phase *Measurements*) | Label now | How it will be measured |
|---|---|---|
| `L_prior` repeatability (same user, repeated) | **PENDING** | ≥ 3 consecutive live calibrations of one developer (`--user-tag`, same set-up). Per hand, report mean, SD, range and CV, plus agreement of every consecutive pair within the relative tolerance. The tolerance is a *candidate* 5 %, To Be Experimentally Determined. Only `MEASURED` per-hand sources count; a DEFAULT fallback is reported, not averaged in. |
| Wizard duration | **PENDING** | `durations_s` of a live calibration (clock `t_mono`; per step and total, including instruction reading and repeats). SYNTHETIC and replay runs record clock `synthetic` / `replay` and are never a duration measurement. |
| Validation-strike detection per zone under Arm A (per calibration) | **PENDING** | `validation.per_zone` of each live calibration: cued, detected, wrong-zone and duplicate commits, and flags. Scored by the reactive arm only. |
| Zone-position variance (Experimental Design) | **PENDING** | Same repeated files: SD of the fit scale and translation and the maximum centre shift per zone. |

Arithmetic (not a measurement): with the default candidate settings, the data windows and countdowns
of an MVP-4 calibration add up to 3 + 5 + 3 + 8 s of windows, 1 + 4 × 5 × 1.5 s of test strikes and
5 × 2 s of countdowns, about 61 s.

## 2. SYNTHETIC machinery check (never evidence)

Five SYNTHETIC calibrations by the scripted actor (seeds 1–5, tip noise 0.002, support noise 0.004
ROI-height units; hidden stick lengths LEFT 0.29 / RIGHT 0.26). This shows only that the pipeline
recovers what the script put in and that the analysis script works:

| hand | L_prior values (5 runs) | mean | SD | range | consecutive pairs within 5 % |
|---|---|---|---|---|---|
| LEFT | 0.2909, 0.2890, 0.2905, 0.2898, 0.2894 | 0.2899 | 0.00079 | 0.0019 | 4/4 |
| RIGHT | 0.2597, 0.2603, 0.2600, 0.2604, 0.2602 | 0.2601 | 0.00026 | 0.0007 | 4/4 |

Fit scale 0.8260 (SD 0.0014); translation x SD 0.0011, y SD 0.0006; max zone-centre shift 0.0016 ROI units. Label: **SYNTHETIC machinery check - never evidence**. Output: `experiments/phase-14/20260926-1047-p14-gate-verification/repeatability/repeatability.{json,md}`.

## 3. DEVELOPER_REPLAY diagnostics (development only)

The three recorded developer swing captures (Phase 02/03; 1.0 m, exposure −5/−6/−7, 171–172 frames)
replayed through the real Phase 03 perception and the wizard, with windows scaled ×0.2 to fit the
captures and validation skipped (no cued behaviour). These are not calibrations of a person following
the wizard.

| capture (1.0 m, L2) | steps (playing area / stick prior / envelope) | hand span px L / R | both hands VALID | stick prior per hand | envelope / fit |
|---|---|---|---|---|---|
| swing-L2-exp-5 | ACCEPTED_WITH_WARNINGS / FALLBACK / PASSED | 27.2 (n=10) / 30.7 (n=31) | 13% | LEFT DEFAULT (accepted 0); RIGHT DEFAULT (accepted 0) | 91 points, fit ENVELOPE scale 0.70 |
| swing-L2-exp-6 | ACCEPTED_WITH_WARNINGS / FALLBACK / FALLBACK | 24.5 (n=10) / 26.1 (n=23) | 0% | LEFT DEFAULT (accepted 0); RIGHT DEFAULT (accepted 0) | none (FIXED template kept) |
| swing-L2-exp-7 | ACCEPTED_WITH_WARNINGS / FALLBACK / FALLBACK | - / - | 0% | LEFT DEFAULT (accepted 0); RIGHT DEFAULT (accepted 0) | none (FIXED template kept) |

Hand-span medians on real frames (24.5–30.7 px, n = 10–31 frames per hand) are of the same order as the Phase 03 1.0 m observation (28–31 px, ADR-0017) and fall inside the candidate advice range 24–38 px. This is a consistency check of the step's unit on few frames, not a distance measurement. The stick prior falls back on swing captures, as designed: they contain no still hold. Exposure −6/−7 lose the hands and the camera step's exposure hint reports TOO_DARK (ROI mean grey 38 / 17 against 74 at −5), matching the Phase 03 exposure finding. Outputs: `experiments/phase-14/20260926-1047-p14-gate-verification/replay/`.

## 4. What the owner must do (developer only; no participants)

1. Calibrate at the usual desk (MVP-4, default settings), three times in a row, re-standing between
   runs:
   `.venv/Scripts/python.exe -m spacedrums.app.calibrate --user-tag dev-<nick> --output data/calibration/dev-<nick>-run1.calib.yaml`
   (then `run2`, `run3`; keep the default output under `data/` so nothing personal is committed).
2. Run `.venv/Scripts/python.exe scripts/calibration_repeatability.py --calibrations data/calibration/dev-<nick>-run*.calib.yaml --output-dir experiments/phase-14/<date>-repeatability`.
3. Play one short session with the best file (`python -m spacedrums.app.main --calibration …`) to confirm
   the calibrated zones are playable, and keep the per-zone validation table of each run.
4. On the committed tree, re-run steps 1–2 (or re-analyse the same files) so the numbers can be cited.
