# ADR-0006 — Per-hand independence as a structural property

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.4 / 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner (Q33–Q35), recorded by Phase 01 |
| Related | `phases/README.md` §8; `docs/architecture/architecture.md` §3, §6 (ownership table, reset matrix); `schemas/track-state.schema.json`; REQ-033, REQ-034, REQ-035, REQ-012 (near-simultaneous hits) |

## Context

Q33 requires each hand to have an independent Tracking, Kinematic and Prediction State. Q34–Q35 require that a tracking loss on one hand leads to a safe `INVALID` state with history reset and no fabricated strike, and that prediction resumes when valid tracking returns. Q12 requires near-simultaneous two-hand hits. A shared or coupled state would make a loss on one hand corrupt the other and would make offline per-hand evaluation (README §10.1, matching per hand) ambiguous.

## Decision

1. `tracking`, `features`, `prediction` and `commit` each instantiate **one state object per `hand_id`** (`LEFT`, `RIGHT`), created at session start, with an explicit `reset(reason)` and a `status` per README §8. Geometry entry episodes are keyed by `(hand_id, zone_id)`.
2. The **reset matrix** (`architecture.md` §6.2) is normative: on `INVALID`/`STALE` the filter state, history window, feature buffers, model hidden state/window, commit FSM state and pending `ARMED` candidates are reset; **refractory timers and last-commit times persist** so a re-acquired hand cannot immediately re-trigger the same zone.
3. `CommitPolicy` refuses every candidate while `status ≠ VALID` (or `∉ {VALID, DEGRADED}` when `allow_degraded_commits` is explicitly enabled as an experiment). This is a property test in the conformance suite (`TEST-CONFORM-5`).
4. Cross-hand interaction is limited to LEFT/RIGHT identity assignment in `hands` and the polyphonic audio mixer. Any future cross-hand rule is a `CommitPolicy` decision (Phase 05) behind the same interface — never a coupling of state objects.
5. Both hands are processed every frame in a fixed order (LEFT, RIGHT) for deterministic logs; the order has no semantic effect.

## Alternatives considered

| Alternative | Why not |
|---|---|
| One tracker with a joint state for both hands (e.g. joint filter with a coupling prior) | Loss on one hand would perturb the other; violates Q33; makes per-hand metrics and resets ambiguous. |
| Reset refractory timers on `INVALID` too | Would allow a re-acquired hand to double-trigger a zone it just hit (a false positive created by the loss itself); persisting timers can only suppress. |
| Allow `DEGRADED` commits by default | Q35's safety intent; kept as a configurable, off-by-default experiment (Phase 05/17). |
| Process hands in parallel threads | Possible later (threading candidate T3 is per stage, not per hand); independence of state is what makes it possible without contract change. |

## Consequences

- Memory and compute scale by exactly two; model hidden states are per hand (Phase 10/13).
- Every record carries `hand_id`; every metric is computed per hand and then aggregated with the aggregation stated.
- Tests: state-machine transition tests (Phase 03), zero-commits-during-INVALID (Phase 05, Task 05.8; Phase 17 failure injection), `TEST-CAUSAL-1/2` per hand.
