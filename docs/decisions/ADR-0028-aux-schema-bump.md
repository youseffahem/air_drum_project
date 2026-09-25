# ADR-0028 — Multi-task aux population, consistency flags, config 1.5 and the C-MT replay arm

Status: IMPLEMENTED contract (Phase 11); reviewer confirmation PENDING at the Phase 11 gate.
Date: 2026-09-25.
Related: ADR-0007 (trajectory first; amendment for the diagnostic direct path), ADR-0008,
ADR-0012, `docs/architecture/contracts.md` §8, REQ-041, REQ-014, REQ-109.

## Context

Phase 11 adds strike-within-H, TTI, zone, impact-position and intensity heads beside the
trajectory head of the Phase 10 encoders. `TrajectoryAux` already reserved nullable fields
for the head outputs. What was missing: a place to record whether the heads agree with the
geometry-derived candidate, a configuration for optional head-based gates that defaults to
off, and a way for the harness to run arm C-MT (and, separately, the labelled no-trajectory
diagnostic) without letting any head create a strike.

## Decision

1. **`TrajectoryPrediction` 1.0 → 1.1** (minor, contracts.md §8). `aux.consistency_flags`
   is added: `null`, or `{zone, tti, position, intensity}` with each value `true`, `false` or
   `null` (head absent). It is computed **after** geometry, by `models/temporal/consistency.py`,
   from the prediction and the candidate geometry derived from that same prediction. Writers
   emit 1.1; readers accept 1.0 and read it as `consistency_flags = null`; a 1.1 record must
   carry the (nullable) field. The schema example is 1.1.
2. **`aux` population rules for C-MT** (`mt_adapter.MultiTaskAnticipator`): every trained
   head fills its field; untrained heads stay `null`. `strike_prob_within_H` = sigmoid of the
   strike logit; `tti` = seconds from `t_capture`, clipped to the supervised [0, H_max];
   `zone_logits` with `zone_ids` in the declared order; `impact_pos` = current tip + predicted
   displacement (ROI units); `intensity_proxy` = train-fold-standardised head output mapped
   back with train-only statistics and clipped at 0 (a proxy, never force).
   `positions` remain the primary output and are decoded exactly as in Phase 10.
3. **Config 1.4 → 1.5**: optional `commit.aux_heads` with `use_p_aux`, `p_aux`,
   `use_agreement`, `agreement_checks`, `tti_tolerance_s`, `position_tolerance`,
   `intensity_tolerance`, `intensity_source`. Absent = all off (`AuxHeadSettings()`);
   the loader rejects the block in documents declaring < 1.5. The Phase 05 `CommitSettings`
   and policy are unchanged; the block is read only by `AuxHeadSettings.from_config`.
4. **Gate semantics** (`consistency.AuxGate`, between geometry and the unchanged policy):
   the head probability never reaches `commit.p_commit` — the gate clears the candidate's
   `strike_probability` and applies `p_aux` itself only when enabled. With agreement enabled,
   every listed check must be `true` (a `null` check fails). `intensity_source = head` swaps
   the committed intensity proxy. The gate can remove or relabel a GEOMETRY candidate and
   refuses any other derivation; it never creates one.
5. **Harness extension** (`eval/replay.py`, additive, defaults preserve every earlier arm):
   arm `MODEL:C-MT`; optional `candidate_gate` after geometry for temporal arms (mandatory for
   C-MT, possibly with every option off); `diagnostic_direct=True` is the only mode in which a
   C-MT model may return `StrikeCandidate(derivation=DIRECT_HEAD)`, it cannot be combined with
   a gate, and the result carries `diagnostic=True` and the label
   *direct / no-trajectory (diagnostic)*. `DirectHeadDiagnostic` is not an `Anticipator`,
   needs `diagnostic=True`, and the application (arms A/B only until Phase 13) never refers
   to it; `MultiTaskAnticipator` refuses packages without the trajectory head
   (`live_eligible = false`).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Put the gate inside `PerHandCommitPolicy` | Frozen Phase 05/09 component; would change every arm's commit code path. |
| Feed the head probability to the existing `p_commit` | Couples a C-MT experiment to the shared B-arm threshold; "defaults off" would not hold. |
| Compute flags inside the model adapter | The adapter may not import geometry (`no-peek`); flags need the geometry candidate. |
| A new record type for flags | A nullable aux field is the documented minor-bump path and keeps flags next to the heads they judge. |

## Consequences

- Phase 05–10 records (1.0) remain valid; new predictions are 1.1 (tested both ways).
- `replay.py` hashes change; the frozen matching/metrics/report/selection/constants and all
  geometry/commit code are unchanged (audited by `scripts/verify_phase11.py`).
- Phase 13 must load `commit.aux_heads`, run `AuxGate` for C-MT, and refuse no-trajectory
  packages (`live_eligible = false`). Gate thresholds and the intensity source remain
  candidates until the Phase 11 participant evidence and ADR-0029/ADR-0030 decisions exist.
