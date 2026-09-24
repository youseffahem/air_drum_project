# Phase 10 failure-case catalogue

Status: PENDING participant catalogue; synthetic diagnostic extraction IMPLEMENTED.

Development example: `experiments/phase-10/synthetic-failure-cases-gru/` contains
`catalogue.json` and `worst-trajectories.png`, produced by `scripts/failure_cases.py`
from horizon cell-036 (candidate GRU N8/K4, fold 0, seed 10). It ranks validation
ADE and plots predicted displacements against actual future causal-track targets.
The export/sample hashes and exact metadata accompany each case.

The companion TCN cell-045 diagnostic is in
`experiments/phase-10/synthetic-failure-cases-tcn/`, generated from the same
candidate fold/grid and inspected visually. It also retains hand-specific case
metadata, export hash, errors, event references and unsupported-category labels.

The scripted sawtooth trajectory reversals expose poor short-training predictions;
these are not participant movement failures or physical tip accuracy. The catalogue
also indexes available FP/FN/wrong-zone and extreme predicted-time events from the
replay. Figures have been visually inspected. Identical left/right fixture tracks
may produce identical ranked cases, distinguished by hand metadata.

PENDING: participant fake swing/stop FPs, fast-hit FNs, adjacent-zone confusion,
tracking-gap and ROI-boundary behavior under real play, unusual-grip outliers, and
actual sound timing. Synthetic tests separately verify gap reset, no-crossing
suppression and future-perturbation invariance; they do not supply these cases.

Frozen TE_pred = predicted impact minus GT impact. A positive value means predicted
impact later than the label. Sound-too-early analysis requires audio evidence and
must not be inferred by reversing that sign. Physical latency remains Phase 18.
