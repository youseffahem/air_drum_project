# Phase 07 — Acoustic onset validation (Task 07.6)

**Status: PENDING / NOT VALIDATED.** No pad and no microphone are inventoried, and no session with a person exists (Phase 06 conditions C-06-3 / C-06-4). **Ground truth in this project is geometric only.** No offset between the geometric impact estimate and a physical impact has been measured, and none is claimed.

**Machinery:** `src/spacedrums/data/labels/acoustic.py`, `scripts/acoustic_onset.py` · **Tests:** `tests/labels/test_label_acoustic.py` (`TEST-LABEL-7`, 10 tests) · **Related:** ADR-0002, `docs/architecture/contracts.md` §6 (`has_phys_gt` three-level invariant)

---

## 1. What the residual would mean

`t_impact_phys − t_impact_est` is the offset between **two differently defined instants**:

* `t_impact_est` — the geometric crossing of a *virtual* impact surface by the *estimated* stick tip, from the reference trajectory;
* `t_impact_phys` — the acoustic onset of the sound a *physical* practice pad made.

It is a **measured offset**, never a claim that the two are the same instant, and it is never applied silently to labels. Every residual is reported with the microphone-path latency bound and the clap-sync residual; a residual smaller than those bounds means nothing.

## 2. The `has_phys_gt` invariant, enforced

Physical ground truth is per **strike**, not per session (`contracts.md` §6). `t_impact_phys` is non-null only when the label is a POSITIVE, inside a `PAD` segment, on that segment's `pad_zone_id`, with an onset paired inside the window. A strike on another zone during a pad segment, or in an AIR segment, has no physical ground truth even when the session has a microphone — verified by `TEST-LABEL-7`.

The schema goes further: a `SYNTHETIC` or `DEV_CAPTURE` label can **never** carry `t_impact_phys`, because no microphone recorded a person.

## 3. Runs (machinery only)

### 3.1 Detector self-test — SYNTHETIC click track with an injected offset

`python scripts/acoustic_onset.py --selftest`: four clicks injected 6.0 ms after four nominal impact instants; the detector recovers 4/4 onsets at +5.0 ms (the 5 ms analysis-frame quantisation of `detect_onsets`). **The recovered offset is the offset that was injected** — this validates the detector and the pairing path and measures no physical latency.

### 3.2 Pairing over the labelled sessions

| Session | Pad positives | Paired | Bias (s) | IQR (s) | Bounds / reason |
|---|---:|---:|---:|---:|---|
| `dev-p06-ingest-exp-5` | — | — | — | — | **PENDING** — session has_phys_gt is false (no microphone track / no PAD segment) |
| `synthetic-p07-labels` | 3 | 1 | 0.04834 | 0.00000 | mic bound 0.005 s, sync 0.01000000000206569 s |

**Reading the table.** `dev-p06-ingest-exp-5` is a DEV CAPTURE with no microphone track: the tool reports the explicit PENDING outcome with its reason rather than a number. `synthetic-p07-labels` carries the **generated** click track that `record_session.py --synthetic --pad-zone` writes, so the pairing path runs end to end; its 48 ms "bias" is the offset between where the generator placed its clicks and where the geometry places the crossing — **a property of the generator, not a measurement of anything physical.** It is listed to show that the pairing, the window, the one-to-one matching and the bounds reporting all work.

## 4. What is required to close this

| Item | Owner | Condition |
|---|---|---|
| Inventory a practice pad and a microphone; record the pad block with claps at start and end | project owner | Phase 06 **C-06-3** |
| Measure and record the microphone-path latency bound (currently the candidate `DEFAULT_MIC_LATENCY_BOUND_S = 5 ms`) | submitter | **C-07-5** |
| Run `scripts/acoustic_onset.py --all` over the campaign; report bias, spread, fraction paired and the number of strikes covered | submitter | **C-07-5** |
| If the condition is dropped: record "dropped" with the evidence; `t_impact_phys` stays null everywhere and the dataset card states that ground truth is geometric only (it already does) | project owner | **C-07-5** |
