# Phase 15 — Visualization / Debug Dashboard

## Status

Planned

## Purpose

Build the developer/debug overlay and dashboard (Q58) that exposes, live and in replay, every internal quantity the research needs to inspect: tracking state, hand landmarks, stick axis and tip (with method id), stick velocity, predicted trajectory, predicted strike and zone, Time-to-Impact, intensity proxy, confidence/probability where applicable, commit decisions (with reasons for rejection), timing information (per-strike decomposition), active arm and fallback status, and capture/audio statistics. Provide export of frames/plots/logs for thesis figures. Measure and bound the overlay's own overhead.

## Why This Phase Exists

Scientific validation requires seeing *why* a strike was or was not committed — bad trajectory, bad geometry crossing, commit gate, refractory, or tracking state. The Phase 03/05 minimal overlays are insufficient for Phase 17 failure analysis, Phase 18 live experiments, and Phase 22's demonstration of the research contribution. The dashboard is also the tool that makes the causal/trajectory-first design visible to reviewers.

## Relationship to Research Contribution

- Visualises the predicted trajectory and its geometric intersection — the core mechanism.
- Displays lead time and timing decomposition per strike in real time (software-stamped), supporting honest communication of what is measured.
- Produces the figures for the thesis and demo (Phases 21–22).

## Inputs

- All record types (Phase 01); Phase 13 application with arms; Phase 04 rendering; timing records; capture/audio stats.

## Expected Outputs

- `ui/overlay` (in-frame overlay) and `ui/dashboard` (side panel / secondary window with plots and tables).
- Replay viewer (scrub a recorded session with all records and labels; optional GT overlay from Phase 07).
- Export tools: annotated frame PNGs, trajectory plots, per-strike timing tables, session summary.
- Overhead measurement (MEASURED) and a "low-overhead mode" for experiments.

## Dependencies

- Phase 13 Exit Gate (may run in parallel with Phase 14).

## System Components

- `src/spacedrums/ui/{overlay.py, dashboard.py, replay_viewer.py, export.py, theme.py}`
- UI framework: OpenCV drawing for the in-frame overlay (already used); dashboard framework = Pending Architecture Decision (candidates: a lightweight Qt/Tk window, or a browser-based panel fed by a local socket); requirement: no impact on the processing loop beyond the measured budget.

## Architecture

```
Processing loop ──► record bus (non-blocking, drop-if-full for UI consumers) ──► overlay renderer (in-frame) 
                                                                             └► dashboard (separate thread/process): plots, tables, logs
replay source ──► same loop in replay mode ──► same UI + GT labels overlay
```

- UI consumers **never** block the processing loop; if the UI falls behind, it drops frames (counted), not the pipeline.
- Overlay elements are individually toggleable; "experiment mode" renders only what Phase 18 protocols require.

## Detailed Tasks

### Task 15.1 — Overlay Elements
- **What:** Per hand: landmarks (toggle), search region, stick axis, tip (colour by `method_id`), filtered tip, velocity vector, tracking state badge (`VALID/DEGRADED/INVALID/STALE`), predicted trajectory polyline (K points; colour by arm), predicted crossing point and zone highlight, TTI countdown text, intensity proxy bar, strike probability (if aux), commit decision markers (committed: flash; rejected candidate: small marker with reason code). Global: zones with impact surfaces and normals, ROI guide, active arm and fallback status, capture FPS/drops, audio underruns.
- **Why:** Q58 list plus prompt §16 list.
- **Depends on:** Records.
- **Evidence:** Screenshots per element; toggle tests.

### Task 15.2 — Timing Panel
- **What:** Per-strike row: arm, hand, zone, `t_capture` of the reference frame, `t_commit`, `t_impact_pred`/`t_impact_est`, `TTI` at commit, software `L_pred` (`t_impact_est − t_commit` when an estimate exists in replay; live shows `t_impact_pred − t_commit` clearly labelled as *predicted* lead), stage latencies, audio scheduling/output estimate; rolling statistics.
- **Why:** README §5; makes the distinction between predicted and estimated impact visible in the tool itself.
- **Depends on:** Timing records.
- **Evidence:** Panel screenshot; label correctness test (live rows never claim `L_pred` against an estimated impact that does not exist yet).

### Task 15.3 — Replay Viewer with Ground Truth
- **What:** Load a recorded session + labels; scrub; step frames; overlay GT impacts (`t_impact_est` marker, zone, position) alongside the arm's candidates/commits; show matched/unmatched status from the harness; export clips.
- **Why:** Failure analysis (Phases 10/17/18) and thesis figures.
- **Depends on:** Phase 07 labels, Phase 09 matching.
- **Evidence:** Viewer opens any `ds-v1.0` session; matched/unmatched rendering verified on a known case.

### Task 15.4 — Plots
- **What:** Live/rolling: tip y-position and vertical velocity vs. time with commit markers; TTI vs. time; per-frame processing time. Replay: predicted vs. actual trajectory over the horizon at selected frames; lead-time histogram for the session; FP list by segment type.
- **Why:** Q45 visualisation needs.
- **Depends on:** 15.3.
- **Evidence:** Plot exports.

### Task 15.5 — Export Tools
- **What:** Annotated PNG frames, SVG/PNG plots, CSV timing tables, session summary JSON; naming with session/arm/model ids.
- **Why:** Phase 21 figures; reproducibility.
- **Depends on:** 15.1–15.4.
- **Evidence:** Exported artefacts from a dev session.

### Task 15.6 — Overhead Measurement and Low-Overhead Mode
- **What:** Measure per-frame processing time and frame drops with overlay off / minimal / full; define "experiment mode" (minimal set) and verify its overhead is within a bound (To Be Experimentally Determined; recorded).
- **Why:** The UI must not alter the timing being measured.
- **Depends on:** 15.1.
- **Evidence:** Overhead table (MEASURED).

### Task 15.7 — Dashboard Framework Decision
- **What:** Prototype the two candidate dashboard approaches minimally; measure loop impact; choose (ADR).
- **Why:** Pending Architecture Decision.
- **Depends on:** 15.6.
- **Evidence:** ADR with measurements.

## Data Requirements

- Recorded sessions for the replay viewer; developer live sessions.

## Algorithms / Technical Approach

- Non-blocking record bus (ring buffers); rendering with OpenCV primitives; plotting via a standard Python plotting library in the dashboard process; SVG export.

## Interfaces / Contracts

- Record bus subscription API; `OverlayConfig` (toggles); export naming convention.

## Tests

- Unit: toggles; label logic in the timing panel; export naming.
- Integration: overlay in live and replay modes; replay viewer on dataset sessions.
- Performance: overhead measurement; UI drop counter increments under load without pipeline drops.

## Measurements

| Quantity | Label |
|----------|-------|
| Overlay overhead per mode (processing time, drops) | MEASURED |
| Dashboard loop impact per framework candidate | MEASURED |

## Experimental Design

- Overhead: same dev session replayed with each overlay mode; compare per-frame processing time distributions.

## Acceptance Criteria

1. All listed overlay elements implemented and toggleable.
2. Timing panel labels predicted vs. estimated correctly.
3. Replay viewer with GT overlay works on dataset sessions.
4. Export tools produce thesis-ready artefacts.
5. Overhead measured; experiment mode within bound; dashboard ADR recorded.

## Definition of Done

- Implementation, tests, overhead measurement, ADR, gate record PASS; integrity checklist applied.

## Risks

- UI rendering in the main loop increases latency → bus + separate thread/process; measured.
- Feature creep → element list is fixed to Q58/§16; extras go to Phase 22 demo polish.

## Failure Modes

- Timing panel shows misleading "lead time" live → label rule and test.
- Replay viewer desynchronises records and video → index by `frame_id`; test.

## Fallback Strategy

- If the dashboard framework is problematic, keep the in-frame overlay + CSV/plot exports only; the requirement is satisfied by the overlay plus exports.

## Artifacts Produced

- `src/spacedrums/ui/…`, `docs/user/debug-overlay.md`
- `docs/reports/phase-15-overhead.md`, `docs/decisions/ADR-<n>-dashboard-framework.md`
- `docs/gates/phase-15-gate.md`

## Exit Gate

Reviewer verifies element coverage, label correctness, overhead. PASS → Phase 16.

## What Must NOT Be Done Yet

- No realistic drum-kit visuals (Phase 22 polish at most).
- No changes to pipeline logic for display convenience.

## Open Questions

- Dashboard framework (Task 15.7).
- Should the overlay show Baseline B's shadow prediction alongside Arm C by default in experiments? (useful for demos; overhead measured)

## Decisions That Must Be Experimentally Validated

- Overhead bound for experiment mode.
- Framework choice.
