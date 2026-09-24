# Phase 10 false-positive controls

Status: PENDING participant experiment; development control machinery IMPLEMENTED.

The synthetic horizon/window runs store full Phase 09 event tables and curves for
tau_commit=.02/.05/.10s, probability=.3/.7 when the auxiliary head is trained,
n_confirm=0/2, inward speed=.15/.30 ROI/s, and zone refractory=.10/.20s.
These are candidate one-knob variations around each reference point, not an
exhaustive Cartesian search or a selected playability configuration.

Pure trajectory carries no strike probability. The optional logit is copied to
the geometry candidate and gated by Phase 05; a high logit with no inward crossing
cannot produce a strike. Temporal direct-head outputs are structurally rejected.
Every result includes lead distribution, positive-lead fraction, FP/min, FN,
timing error/bias, zone accuracy, impact-position and intensity diagnostics,
and available segment attribution from the unchanged harness.

The existing fixture contains scripted generic unit segments, not participant
fake swings, stops, adjacent-zone mistakes or a playability campaign. Their FP
attribution is PENDING, not zero. No budget or best control is selected from the
fixture. [ADR-0025](../decisions/ADR-0025-fp-budget.md) and the
[pre-registration](../experiments/phase-10-prereg.md) retain the owner's budget decision.
