# Architecture Decision Records — Index

Format: `ADR-NNNN-<slug>.md`, each with Context, Decision, Alternatives considered, Consequences, and a Status (Proposed / Accepted / Superseded by ADR-NNNN / Deprecated). ADRs are append-only; a changed decision is a new ADR that supersedes the old one.

When an ADR is required: any decision not already in `project-discovery.md`; any stack change (`docs/environment.md`); any scope re-inclusion (`docs/requirements/out-of-scope.md` §2); any layout amendment (`docs/repo-layout.md`); any contract or config schema bump (`docs/architecture/contracts.md` §8); model-family / ship decisions (Phases 10–13); results of `Pending Architecture Decision` markers.

| ADR | Title | Status | Date | Phase |
|---|---|---|---|---|
| [ADR-0001](ADR-0001-python-first-stack.md) | Python-first technology stack | Accepted | 2026-09-20 | 00 |
| [ADR-0002](ADR-0002-practice-pad-microphone-ground-truth.md) | Optional practice-pad + microphone physical-impact ground truth | Accepted | 2026-09-20 | 00 |
| [ADR-0003](ADR-0003-mvp-zone-set.md) | MVP and V1 virtual drum-zone set (7th zone: Open Question) | Accepted (partial) | 2026-09-20 | 00 |
| [ADR-0004](ADR-0004-single-monotonic-clock.md) | Single monotonic clock `t_mono` for every timestamp | Accepted | 2026-09-20 | 01 |
| [ADR-0005](ADR-0005-roi-normalized-y-down-coordinates.md) | ROI-normalized, y-down, 2-D coordinate convention | Accepted | 2026-09-20 | 01 |
| [ADR-0006](ADR-0006-per-hand-independence.md) | Per-hand independence as a structural property (ownership + reset matrix) | Accepted | 2026-09-20 | 01 |
| [ADR-0007](ADR-0007-trajectory-first-geometry-stage.md) | Trajectory first: geometry is a separate deterministic stage after prediction | Accepted (amended at gate review: labelled diagnostic direct path) | 2026-09-20 / 2026-09-21 | 01 |
| [ADR-0008](ADR-0008-candidate-source-abstraction.md) | Candidate-source abstraction: one geometry + one commit policy for arms A/B/C | Accepted | 2026-09-20 | 01 |
| [ADR-0009](ADR-0009-threading-model-candidates.md) | Threading model: T1 baseline adopted; T2/T3 Pending Architecture Decision (Phase 16) | Accepted (T1) / Pending (T2, T3) | 2026-09-20 | 01 |
| [ADR-0010](ADR-0010-configuration-schema.md) | Configuration: one schema-validated resolved document; candidate vs frozen files | Accepted | 2026-09-20 | 01 |
| [ADR-0011](ADR-0011-zone-registry-extensibility.md) | Zone-registry extensibility: open trigger-type enum, generic geometry, hand-agnostic zones | Accepted | 2026-09-20 | 01 |
| [ADR-0012](ADR-0012-record-contracts-json-schema.md) | Record contracts as versioned JSON Schemas; type-only packages added to the layout | Accepted | 2026-09-20 | 01 |
| [ADR-0013](ADR-0013-capture-backend-timestamp-policy.md) | Capture backend, timestamp policy, duplicate refusal, config schema 1.1 (HW-01 measurements) | Accepted (backend choice = candidate until Phase 03) | 2026-09-21 | 02 |
| [ADR-0014](ADR-0014-hand-landmarker-wrapper.md) | Hand-landmark estimator wrapper: MediaPipe Tasks candidate, model-asset pinning (`assets/models/`), config schema 1.2 (`hands` block), raw-label emission rule | Accepted; Decision 8 closed by the owner check; amended by Tasks 03.2 (§10 identity) and 03.3 (§12 grip) — values remain candidates until Tasks 03.10/03.11 complete | 2026-09-21 | 03 |
| [ADR-0015](ADR-0015-primary-tip-method.md) | Markerless stick pipeline (`stick` block) and primary tip method — **provisional `GEOM`** pending the annotated benchmark (gate C-03-1 PENDING) | Accepted (pipeline) / Provisional (primary method) | 2026-09-21 | 03 |
| [ADR-0016](ADR-0016-filter-choice.md) | Per-hand causal filter (`kalman_cv` candidate) and README §8 state machine; TEST-CAUSAL-2 `N_eff` declaration rule | Accepted (thresholds = candidates) | 2026-09-21 | 03 |
| [ADR-0017](ADR-0017-roi-distance.md) | ROI / user distance for data collection: keep 1.0 m, 640×480, exposure −5 at L2; factorial PENDING (gate C-03-3) | Proposed (recommendation) | 2026-09-21 | 03 |

Next free number: **ADR-0018**.
