# spacedrums.prediction

**Status:** rule-based arm B IMPLEMENTED (Phase 05, Task 05.2; ADR-0018): `AnticipatorBase` (common gates, decline reasons, declared `TEST-CAUSAL-2` window) and `RuleBasedAnticipator` (CV / CA extrapolation from the tracker's causal history, heuristic monotone `strike_probability`, `RuleSettings.from_config` validating `anticipator.rule.params`). Learned arms (C-GBDT, C-GRU/TCN/MT/TT): Phases 09–12.

Layer L5: imports L0 and tracking types; **never** `geometry` (import-linter contract `no-peek`). Tests: `tests/prediction/` (analytic crossing vs synthetic parabola, conformance `TEST-CONFORM-3`, gate monotonicity, failure cases, `TEST-CAUSAL-1/2`). Every threshold is a playability candidate (`configs/prototype.candidate.yaml`).
