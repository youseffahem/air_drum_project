# spacedrums.prediction

Phase 13 adds `ModelArm` (injected temporal adapter, per-hand windows and stamps),
`model_loader` (manifest/export/statistics verification), `budget_monitor` (sliding
p95 and delivered-cadence checks) and sticky `fallback` events. The app owns model
and feature construction so prediction keeps its no-geometry import boundary.
GRU/TCN integration is IMPLEMENTED as development machinery; the shipped package
and full Phase 13 gate remain PENDING. See ADR-0036 and `tests/parity/`.

**Status:** rule-based arm B IMPLEMENTED (Phase 05, Task 05.2; ADR-0018): `AnticipatorBase` (common gates, decline reasons, declared `TEST-CAUSAL-2` window) and `RuleBasedAnticipator` (CV / CA extrapolation from the tracker's causal history, heuristic monotone `strike_probability`, `RuleSettings.from_config` validating `anticipator.rule.params`). Learned arms (C-GBDT, C-GRU/TCN/MT/TT): Phases 09–12.

Layer L5: imports L0 and tracking types; **never** `geometry` (import-linter contract `no-peek`). Tests: `tests/prediction/` (analytic crossing vs synthetic parabola, conformance `TEST-CONFORM-3`, gate monotonicity, failure cases, `TEST-CAUSAL-1/2`). Every threshold is a playability candidate (`configs/prototype.candidate.yaml`).
