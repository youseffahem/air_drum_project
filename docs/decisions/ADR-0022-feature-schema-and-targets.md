# ADR-0022 — Causal feature schema, bounded state and target separation

Status: IMPLEMENTED as engineering choices; empirical choices are candidates. Date: 2026-09-22.
Owner: Phase 08. Related: ADR-0012, ADR-0021, `docs/features/feature-schema-v1.md`.

The existing TrackState contract omits hand landmarks, raw axis confidence, apparent stick
length and capture drops. Adding inferred replacements would hide missing inputs. Accept
optional same-frame HandObservation, StickObservation and FrameSample at the feature boundary;
join them offline by frame/hand and reject time or identity mismatches. Preserve the TrackState
contract and mask missing observations. Runtime app integration belongs to Phase 13.

The core is bounded to two TrackStates (three for optional jerk). Keep elapsed-window time in
the shared window assembler, since a global elapsed clock would violate history truncation.
INVALID/STALE reset derivative history and mask all fields; their records remain in the ring
so the window can distinguish missing observations from zero motion.

Use fs-v1 with a descriptor hash to distinguish layout/order, groups and numerical parameters.
Default MVP4 F=56; seven zones F=71; optional jerk adds three. Angles use sine/cosine. Candidate
normalization is median/IQR for velocity/acceleration/jerk, z-score for other continuous fields,
identity for direction/angle/flags/time. Fit per fold on eligible training frames only.

The feature core has no label or dataset access. A higher-layer offline loader combines causal
features with target-only labels and frozen splits. Primary trajectory targets are future causal
TrackStates; geometric strike labels supervise only auxiliary targets. Tail censoring, rejected
labels, ambiguity, quarantine and tracking discontinuities are explicit masks. Excluded histories
are retained for later safety analysis. No decision pipeline or learned model is implemented.

Config schema 1.4 adds an optional features block; old configurations remain readable. The
feature-bearing configuration requires 1.4, and H<=H_max and g_win<=N are checked. The two narrow
import-linter exceptions to geometry.zones implement the read-only dependency already allowed
by architecture §2.2. They do not allow feature code to generate candidates.

No reference-trajectory input or future smoothing is allowed. No participant data exists, so
normalization choice, HAND subset, jerk, g_win and all N/K/H sweep selections await Phases 09/19.
No new participant recording, manual annotation, consent record or empirical result was created.
