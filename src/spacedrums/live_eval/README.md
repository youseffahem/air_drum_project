# spacedrums.live_eval

**Phase 18 (Evaluation & Experiments).** Status: IMPLEMENTED development machinery, exercised only
on SYNTHETIC rehearsals. No participant or live-person result exists. See the
[pre-registration](../../../docs/experiments/phase-18-prereg.md),
[ADR-0042](../../../docs/decisions/ADR-0042-phase18-evaluation-design.md) and the
[Phase 18 gate](../../../docs/gates/phase-18-gate.md).

The Phase 09 harness `spacedrums.eval` is **frozen**. This package builds on its outputs and never
changes a harness rule.

| Module | What it does |
|---|---|
| `prereg` | Append-only hash record of the pre-registration (CRLF-normalised SHA-256), frozen-inputs lock validation and archiving (schema `confirmatory-lock`), and the execute-once ledger |
| `stats` | Participant bootstrap: 10,000 resamples, seed 18, 95 %; paired differences; the pooled-ratio interval for FP/min. P ≤ 3 intervals are flagged as degenerate |
| `hypotheses` | The declared decision rules H1a, H1b, CB, H2, H3, H4, H4-B, with failure readings |
| `offline` | Per-participant / pooled regrouping of harness events; strata (hand, zone, segment, speed tercile, lighting, distance); sensitivity S1 (README §10.1 reference time); causal-target ADE / FDE; event summaries for the figures |
| `causality` | TEST-CAUSAL-1 (GARBAGE / REMOVED / SHIFTED) on any replay callable, with effectiveness counts |
| `counterbalance` | Williams designs: arm orders and balance reports |
| `protocol` | The live protocol: arm blocks of Phase 06 segments, and `ArmSwitcher` (sounding arm per block, blinded participant text) |
| `metadata` | `LiveSessionMetadata`: `live-session.json`, extending Phase 06 `SessionMetadata` by composition |
| `sync` | Clock maps, event-train alignment, flash detection, envelope cross-correlation |
| `acoustic` | M1: template location of played samples, pad onsets on the residual, strike pairing, click-pair validation, the declared GO rule |
| `video` | M2: brightness series from a video file, frame-quantised latencies, the declared GO rule |
| `software` | M3: README §5.3 decomposition per arm and per-strike software estimates (SOFTWARE ESTIMATE; mixed-clock records rejected) |

Layering: a sibling of `spacedrums.app` in the top layer (`.importlinter`). It may import `eval`,
`data`, the pipeline packages and `audio`, but never the application. The scripts
`run_live_session.py`, `external_sync.py`, `analyze_live.py`, `run_offline_confirmatory.py` and
`confirmatory_lock.py` compose it with the app and the models.

Tests: `tests/live_eval/` (stats and rules, pre-registration, methods, live protocol, offline
layer) and `tests/scripts/test_phase18_scripts.py`. All of them use constructed or SYNTHETIC inputs.
