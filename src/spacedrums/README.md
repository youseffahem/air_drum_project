# spacedrums

Phase 09 adds a development evaluation harness (`eval`) and a flattened-window
LightGBM baseline (`models.gbdt`). Participant-fold measurements and the Phase 09
exit gate remain pending the reviewed `ds-v1.0` dataset.

**Status:** first code landed in Phase 02 (`capture`, `ui.guide`, and the L0 packages `contracts`, `timing`, `config`); Phase 03 adds `hands`, `stick`, `tracking`, the minimal `ui.overlay`, and the `HandObservation` / `StickObservation` / `TrackState` records with the `TipEstimator` / `Tracker` Protocols; Phase 04 adds `geometry` and `audio`; Phase 05 adds `prediction` (rule-based arm B), `commit`, the `timing` collector/streams/decomposition, `capture.ReplayFrameSource` and the composition root `app`. `features`, `eval`, `data`, `calib` are PLANNED stubs whose README names the owning phase.

Layout and the allowed-dependency layers: `docs/architecture/architecture.md` section 2 (enforced by `.importlinter` + `tests/architecture/`). `pyproject.toml` carries the `[project]` table since Phase 02; install for development with `python -m pip install -e .` (documented in `docs/environment.md` section 4). Version `0.<phase>.<patch>`.

| Package | Status | Phase |
|---|---|---|
| `contracts` | IMPLEMENTED (enums, `FrameSample`/`ImageRef`, `HandObservation`, `StickObservation`, `TrackState` (P03), `FrameView`, `FrameSource` / `TipEstimator` / `Tracker` Protocols, schema access) | 01 spec / 02 code; later records by their producers |
| `timing` | IMPLEMENTED (`now()`, `CLOCK_ID = perf_counter`, CPU-time/sleep/wall-clock helpers) | 02; `TimingRecord` collector in 05 |
| `config` | IMPLEMENTED (fragment merge, schema validation, cross-field checks, `config_hash`, resolved snapshot) | 02 |
| `capture` | IMPLEMENTED (`LiveFrameSource`, backends, ROI helper, queue, stats, timestamp mapping, device probing) | 02 |
| `hands` | IMPLEMENTED: `HandLandmarker` wrapper + coordinate boundary (03.1), `IdentityAssigner` (03.2), grip reference points (03.3) | 03 |
| `stick` | IMPLEMENTED: search region, segmentation, axis, `GEOM` / `AXIS_REFINED` / `MARKER` tip estimators (03.4–03.9); primary method provisional (ADR-0015) | 03 |
| `tracking` | IMPLEMENTED: filters, README §8 state machine, `CausalTracker` (03.12–03.13; ADR-0016) | 03 |
| `ui` | `guide.py` (02) + minimal debug `overlay.py` (03.15) IMPLEMENTED; zones (04) / full dashboard (15) PLANNED | 02 / 03 / 04 / 15 |
| `geometry`, `audio` | IMPLEMENTED (Phase 04; gate proposed FAIL on the audio-latency criterion) | 04 |
| `prediction` | IMPLEMENTED: `RuleBasedAnticipator` (CV/CA, heuristic probability, `TEST-CAUSAL-1/2`) — arm B | 05 (learned arms 09–12) |
| `commit` | IMPLEMENTED: `PerHandCommitPolicy` + zone state machine + refractory timers (shared by every arm) | 05 |
| `app` | IMPLEMENTED: `DecisionPipeline`, CLI with live/replay/dev-capture/synthetic sources, record mode, session summaries | 05 (13 adds arm C) |
| `data` | IMPLEMENTED (Phase 06 machinery: protocol, metadata, recorder hooks, audio capture, validation, manifests; no participant data) | 06 (07 adds labels / splits) |
| `features` | IMPLEMENTED development feature pipeline; participant statistics pending | 08 |
| `eval`, `models.gbdt` | IMPLEMENTED development harness/model; participant results pending | 09 |
| `calib` | PLANNED stub | 14 |
