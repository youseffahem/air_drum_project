# ADR-0003 — MVP and V1 virtual drum-zone set

| Field | Value |
|---|---|
| Status | **Accepted** for MVP and V1 core; 7th V1 zone is an **Open Question** (formalised in Phase 00, Task 00.9) |
| Date | 2026-09-20 (recorded) |
| Deciders | Project owner |
| Related | `project-discovery.md` Q16, Q17, Q55; REQ-016, REQ-017, REQ-055, REQ-207; Phase 04 (zone registry), Phase 14 (calibration layouts) |

## Context

Q16 asks for ≈ 4 zones in the MVP and ≈ 7 in V1, with the exact arrangement confirmed before implementation. Q17 lists six drums (Snare, Hi-Hat, Tom 1, Tom 2, Floor Tom, Crash/Ride) and defers Kick because foot tracking is outside V1 (Q55). Zone *count* affects the difficulty of Zone Accuracy (README §10.2), the layout of the playing ROI, and the dataset protocol (Phase 06 must exercise every zone).

## Decision

| Set | Zones | Count |
|---|---|---|
| **MVP** (Phase 04/05 first playable) | **Snare, Hi-Hat, Tom 1, Crash/Ride** | 4 |
| **V1 core** | MVP + **Tom 2, Floor Tom** | 6 |
| **V1 seventh zone** | **Open Question** — candidates: (a) split Crash/Ride into **Crash** and **Ride** (most conventional; keeps everything hand-played); (b) a **Kick** zone triggered by a *hand* gesture (deviates from real kit ergonomics; not foot tracking so does not violate REQ-207); (c) **Cowbell / auxiliary** percussion; (d) stay at 6 and report "≈ 7" as 6 with justification. Decision deferred to the Phase 04 gate after the ROI size and per-zone accuracy are first observed; recorded then as ADR-0003 amendment or a new ADR. | 6 or 7 |

Rules attached to the decision:

- Zone identities are stable **string ids** (`snare`, `hihat`, `tom1`, `tom2`, `floor_tom`, `crash_ride`, …) in the Phase 04 registry; layouts (positions/sizes) are versioned config files (`configs/zones.<variant>.v<N>.yaml`), not code.
- The registry **must reserve** the possibility of a future `kick` zone with a non-hand trigger source (Q55) without implementing it — tagged `OOS-REF:REQ-207` in the code (`out-of-scope.md` §3).
- Either hand may hit any zone (REQ-011); no hand–zone assignment in MVP/V1 unless Phase 18 evidence changes it.
- Each zone maps to one local drum sample in the MVP; a Crash/Ride combined zone uses a single sample chosen in Phase 04 (candidate: crash).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Start with all 6–7 zones in the MVP | Slower first playable; harder to debug tracking/geometry with a crowded ROI; the research question does not depend on zone count. |
| MVP with 2–3 zones (Snare, Hi-Hat only) | Too easy for zone accuracy and unrepresentative of "movement between zones" negatives (REQ-048). Four gives left/right and up/down separation. |
| Include Kick via foot tracking | Out of scope (REQ-207). |
| Fixed hand–zone assignment | Contradicts Q11 unless experiments show benefit. |

## Consequences

- Phase 04 implements the registry with the six ids above and a reserved kick slot; the MVP layout file contains four.
- Phase 06 protocol must cover all V1 core zones from every participant so that Zone Accuracy is measurable per zone.
- Zone Accuracy results must state the zone count they were obtained with (4 vs 6/7) — never compared across counts without saying so.
- The 7th-zone Open Question is carried in `docs/gates/phase-00-gate.md` and resolved no later than the Phase 04 gate.
