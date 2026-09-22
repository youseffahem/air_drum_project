# `spacedrums.eval` — Phase 09 development harness

`replay.py` steps through causal TrackStates in capture order. It feeds the Phase 04
`GeometryEngine` and Phase 05 `PerHandCommitPolicy` directly for A, B or a model
adapter. State is fresh per call and per hand. A delay policy supplies zero, fixed
or recorded per-frame processing delays. A model sees only current/past tracks and
the current causal feature window; target labels enter only after replay.

`matching.py` implements deterministic one-to-one matching per session and hand.
`metrics.py` provides event, timing, zone, intensity, trajectory and active-time
measures with explicit nulls for undefined denominators. `report.py` stratifies
by hand, zone and segment and writes JSON and Parquet event records. `curves.py`
plots achieved operating points without interpolation. The current W default is
a candidate: `constants.W_PRIMARY_S` is unset until participant validation.

Run `scripts/verify_phase09.py` for the available synthetic/developer evidence.
That run cannot close the phase gate: frozen `ds-v1.0` folds and reviewed participant
labels do not exist in this workspace.

## Adding an arm

Implement a callable taking `(current_track, causal_history, current_feature_window)`
and returning a `TrajectoryPrediction`, a sanctioned diagnostic `StrikeCandidate`,
or `None`. Add its arm id to `replay`, map it to the contract `Arm` enum, and keep
the same `GeometryEngine` and `PerHandCommitPolicy` path. Supply aligned causal
feature records and fold-train normalization; do not pass labels into the
callable. Run the future-perturbation and known-answer tests, then evaluate with
the frozen W and delay policies. Model files and result manifests must carry
their hashes and participant split identities.
