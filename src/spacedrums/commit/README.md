# spacedrums.commit

**Status:** IMPLEMENTED (Phase 05, Task 05.3; ADR-0018): `ZoneCommitMachine` (IDLE → ARMED → COMMITTED → REFRACTORY; episode bookkeeping for anticipatory commits), `RefractoryTimers` (per zone / per hand; persist across resets except `SESSION_START`), `PerHandCommitPolicy` (the `CommitPolicy` implementation: status, frame-drop, zone, stale, probability, TTI, refractory, episode and hysteresis gates; one instance per hand per arm; `shadow` flag). `CommitSettings.from_config` reads the `commit` block.

Layer L6: imports L0, `geometry` (registry, "inside" test) and tracking types; never perception / prediction / features (import-linter contract `commit-blind`). Tests: `tests/commit/` (every transition and gate, `TEST-CONFORM-5` property test, `TEST-CAUSAL-1/2`).
