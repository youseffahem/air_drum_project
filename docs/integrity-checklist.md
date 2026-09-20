# Research Integrity Checklist

**Phase:** 00 — Task 00.6 · **Status:** IMPLEMENTED (checklist in use from the Phase 00 gate onward)
**Applied at:** every Exit Gate ([`gates/gate-procedure.md`](gates/gate-procedure.md) step 3) and before any document, figure, or claim is shared outside the project.
**Source:** `project-discovery.md` Q60 (REQ-060a–d); `phases/README.md` §4 and §13.

Each item is answered **YES / NO / N/A** with a one-line pointer to evidence. A single **NO** blocks a PASS verdict (the gate may still be PASS-WITH-CONDITIONS only if the item is N/A for the phase or the reviewer documents why the NO is acceptable and by when it will be fixed).

## The checklist

| # | Item | Check performed by the reviewer | Evidence pointer (fill in) |
|---|---|---|---|
| **I-1** | **Every number is labelled** Target / Measured / Historical / Pending (README §4), and every Measured number cites method, date, hardware id, and config/run id. | Grep the phase's artefacts for digits; each occurrence is either quoted from `project-discovery.md`, marked *candidate* / *sweep value* / *tunable*, or carries a label and a `run_id`. | |
| **I-2** | **No claim of implementation without tests.** Anything called IMPLEMENTED has tests that exist and pass in the cited commit. | Test report attached to the gate; `git_sha` named; CI or local run log. | |
| **I-3** | **No causal component consumes future frames.** Every component labelled causal passes the future-perturbation invariance test defined in Phase 01 (Task 01.x, `TEST-CAUSAL-*`): perturbing frames with `t_capture > t_now` changes nothing in the output at `t_now`. Offline label generation (Phase 07) is the only documented non-causal path. | Test id + result; for phases without code: N/A with reason. | |
| **I-4** | **No fabricated data.** No recording, dataset sample, participant, label, or result was invented, simulated-and-presented-as-real, or copied from elsewhere. Synthetic data, if any, is labelled synthetic in the file name and the document. | Dataset manifest hashes; participant consent records exist for every participant id; example/synthetic files carry `example`/`synthetic` in their names. | |
| **I-5** | **FPS reported as native only.** Any frame-rate figure is the camera's measured native delivery rate (Phase 02 method); no interpolated, upsampled, or "effective" FPS is presented as FPS. | Camera profile cited; method named. | |
| **I-6** | **No "latency reduced" claim before Phase 18.** Effective latency (`L_eff`) is described only as a conceptual relation (README §5.4) until Phase 18 measures `t_audio_out` / `t_acoustic_onset` against `t_impact_est` / `t_impact_phys`. Never claim sound is guaranteed before physical impact (REQ-060c). | Grep for "reduce", "reduced", "faster", "before impact", "guarantee" in the phase's documents. | |
| **I-7** | **Marker condition clearly labelled.** Every result obtained with coloured tape / markers is labelled *fallback* or *benchmark/controlled condition* and is never presented as the markerless system's result (REQ-009, REQ-211). | `tip_method` field on every cited result; captions/labels checked. | |
| **I-8** | **Participant-level split confirmed** for any ML result: `train ∩ val ∩ test = ∅` at participant level; normalisation statistics computed on training participants only; split file version named. | `split{}` block in the cited `run.json`; leakage test id (Phase 08). | |
| **I-9** | **Scope respected.** Nothing from `requirements/out-of-scope.md` was built, benchmarked, or claimed without the re-inclusion procedure; every intentional contact carries an `OOS-REF` tag. | `grep -r "OOS-REF"` output reviewed; ADR list reviewed. | |
| **I-10** | **Status vocabulary correct.** Every artefact and requirement touched by the phase carries exactly one of PLANNED / IMPLEMENTED / MEASURED / VALIDATED / PENDING, and the phase document's `## Status` line matches the gate verdict. | Phase document and RTM rows checked. | |
| **I-11** | **Reproducibility fields complete** for every cited run: `run.json` validates against the schema, `git_dirty: false`, config snapshot present, hashes present (`reproducibility-policy.md` §4–§5). | Validation output attached. | |
| **I-12** | **Limitations stated.** The phase's documents list what was *not* shown, what remains Pending, and known failure modes; no result is generalised beyond its measured conditions (lighting, distance, participants, hardware). | Section present and non-empty. | |

## Usage notes

- The checklist is copied into each gate record (`docs/gates/phase-XX-gate.md`) and filled there; this file stays the unfilled master.
- Items may be added (never removed) by ADR. Additions apply to all subsequent gates.
- For Phase 00 itself, items I-3, I-5, I-7, I-8 are N/A (no code, no camera, no data) and are recorded as such in `gates/phase-00-gate.md`.
