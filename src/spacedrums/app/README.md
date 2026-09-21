# spacedrums.app

**Status:** IMPLEMENTED (Phase 05, Task 05.5; ADR-0018). Composition root (layer L8): the playable prototype.

- `pipeline.DecisionPipeline` — per frame: tracking (both hands) → Phase 04 geometry on the observed trajectory (arm A) → rule-based extrapolation + the same geometry (arm B) → one commit policy per arm per hand → audio for the active arm → `TimingRecord`s. Consumes observations, so it runs on live perception, replay and labelled SYNTHETIC sequences alike.
- `main` — CLI: `--source live | replay | devcapture`, `--synthetic <scenario>`, keyboard `a`/`b` arm switch, `--record` (record mode), `--no-audio`, `--audio-output-latency-s` **only with** `--audio-latency-run-id` (otherwise the DAC estimate is withheld), `--replay-delta-proc-s` (provisional replay `t_now`).
- `audio_out.AudioOutput` — scheduler + sample bank + mixer + device with explicit `OutputLatency` provenance (PENDING on HW-01).
- `recorder.SessionRecorder` — frames (lossless PNG) + `frames.jsonl` + header-first record streams + `timing.jsonl` + `config.snapshot.yaml` + `session.json` (Phase 05 developer provenance; not the Phase 06 `SessionMetadata`).
- `session_summary` — counts, README §5.3 decomposition, informal B-vs-A comparison, SYNTHETIC-truth evaluation, non-VALID commit count (developer sanity-check machinery; Phase 09 owns the canonical harness).
- `synthetic` — deterministic SYNTHETIC observation sequences and scenarios (never evidence).

Tests: `tests/app/`. Scripts: `scripts/playability_session.py`, `scripts/induced_loss_test.py`, `scripts/timing_summary.py`, `scripts/shadow_compare.py`, `scripts/rule_baseline_sensitivity.py`, `scripts/render_session_frames.py`. Phase 13 adds arm C.
