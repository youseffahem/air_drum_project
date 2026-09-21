# spacedrums

**Status:** first code landed in Phase 02 (`capture`, `ui.guide`, and the L0 packages `contracts`, `timing`, `config`); Phase 03 adds `hands`, `stick`, `tracking`, the minimal `ui.overlay`, and the `HandObservation` / `StickObservation` / `TrackState` records with the `TipEstimator` / `Tracker` Protocols. Every other subpackage is still a PLANNED stub whose README names the owning phase.

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
| `features`, `geometry`, `prediction`, `commit`, `audio`, `eval`, `data`, `calib`, `app` | PLANNED stubs | 04+ |
