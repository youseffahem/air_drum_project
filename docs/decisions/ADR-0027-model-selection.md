# ADR-0027 — Phase 10 model-family selection

Status: PENDING participant CV comparison and reviewer decision.
Date: 2026-09-24.

No model family, history length, horizon, loss, auxiliary setting, sampler or
operating point is selected. A/B/C-GBDT are eligible winners. Synthetic training
demonstrates implementation behavior only, including legitimate poor prediction.

Selection must weigh participant-macro lead median/IQR/positive fraction, FP/min
and attribution, FN, timing MAE/bias, zone accuracy, ADE/FDE support, impact-position
error, intensity agreement, CPU p50/p95/p99, parameter/storage cost and seed variance.
Apply all predeclared bounds before maximizing lead; report per-participant paired
differences/CIs and sparse positives. A simpler feasible arm may be preferable.

The optional auxiliary head gates a trajectory-derived candidate. The MODEL-only
wrapper computes intensity from the geometry-derived crossing velocity dotted
with the zone's inward normal. Phase 04's existing magnitude-based proxy and
Phase 05 policy remain unchanged; comparison reports must state that distinction
when interpreting intensity, particularly for oblique motion.

TorchScript was chosen for development export because it is available in the
pinned CPU environment and allowed by this phase. Installed PyTorch emits a
deprecation warning; parity and artifact hashes are tested. ONNX is not claimed.
No alternative deployment runtime, Transformer, uncertainty or live integration
has been added. A clean-environment participant reproduction is still required.
