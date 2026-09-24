# Codex Model Selection Guide

## Purpose

This guide documents recommended Codex execution profiles for Space Drums Phases 10–23. The recommendations are based on each complete Phase specification and its implementation, test, evidence, and exit-gate workload. They are planning advice, not a record of execution.

## Rules

- Select the model and reasoning effort in the Codex picker before running a phase; document text does not switch the active setting.
- Record the actual model and reasoning effort, execution date/time with timezone, starting and final-verification Git HEAD SHAs, and git_dirty state in the Phase evidence.
- If the recommendation is unavailable, use the strongest available compatible model within the project reasoning limit and record the actual setting and deviation.
- Model selection does not replace tests, acceptance criteria, empirical evidence, or human review.
- Do not claim a recommended profile was actually used unless the execution evidence records it.

### Selection Rules

1. Choose the model from the actual algorithmic, repository, dependency, research, realtime, debugging, verification, documentation, and autonomous-work workload.
2. Choose reasoning effort independently from the model. Every Phase here recommends either High or Extra High.
3. Reserve Extra High for sustained reasoning across difficult ML, causal evaluation, realtime behavior, complex failure analysis, or whole-system integration.
4. Extra High is the maximum allowed project setting.
5. Ultra and Max must not be recommended.
6. A recommendation does not switch the active Codex model; the user must set it in the picker.
7. Record the model and reasoning effort actually used in Phase evidence.
8. Tests, acceptance criteria, empirical evidence, and human review remain mandatory regardless of model.

## Phase Matrix

| Phase | Workload | Recommended Model | Reasoning | Rationale |
|---|---|---|---|---|
| [Phase 10](../phases/phase-10-temporal-ai.md) | Deep ML / Temporal Modeling | GPT-6 Astra | Extra High | The core phase designs causal GRU/TCN trajectory models, masked sequence windows, stateful inference, export parity, and a multi-criteria horizon/operating-point sweep against the frozen Phase 09 harness. Astra supports the end-to-end ML and code work; Extra High is justified by sustained leakage, temporal-contract, and evaluation reasoning before the single held-out test run. |
| [Phase 11](../phases/phase-11-multitask-prediction.md) | Deep ML / Multitask Learning | GPT-6 Astra | Extra High | Shared-encoder training introduces masked losses, task conflicts, loss-weight search, head ablations, and geometry-consistency gates across several target semantics. Astra fits the research and implementation workload; Extra High is justified by the coupled optimization and leakage-sensitive joint evaluation while preserving the live trajectory-first invariant. |
| [Phase 12](../phases/phase-12-trajectory-extensions.md) | Deep ML / Trajectory Prediction | GPT-6 Astra | Extra High | If this optional phase is attempted, causal attention, longer horizons, multimodal trajectories, uncertainty propagated through geometry, and decoding changes each need CPU feasibility and pre-declared go/no-go comparisons. Astra fits the experimental architecture work; Extra High is justified for reasoning across those interacting representations, causality tests, and baseline comparisons. A documented skip requires no model execution. |
| [Phase 13](../phases/phase-13-realtime-inference.md) | Realtime ML Systems | GPT-6 Astra | Extra High | Live Arm C joins model hashes and feature schemas with per-hand streaming state, variable frame intervals, worker delay, fallback, and audio timing. Astra fits the full-pipeline integration; Extra High is justified by causality, dropped-frame safety, and frame-by-frame offline/online parity across interacting runtime states. |
| [Phase 14](../phases/phase-14-calibration.md) | Computer Vision / Runtime Calibration | GPT-6 Astra | High | The wizard must fit an ROI, per-hand stick priors, and deterministic zone geometry while keeping the calibrated ZONE features and session hashes compatible with the live model. Astra fits the cross-module CV work; High is sufficient because the algorithmic choices are bounded by existing tracking, geometry, and Arm A validation contracts. |
| [Phase 15](../phases/phase-15-debug-dashboard.md) | Engineering / Observability | GPT-6 Sol | High | The dashboard consumes existing records for overlays, replay, timing labels, and exports, with a non-blocking bus and measured UI overhead. Sol fits this well-specified integration workload; High covers replay alignment, predicted-versus-estimated timing labels, and the requirement to leave the causal production path unchanged. |
| [Phase 16](../phases/phase-16-optimization.md) | Performance Engineering / Realtime Optimization | GPT-6 Astra | Extra High | Threading or multiprocessing, model quantisation, and native-FPS handling can alter frame order, predictions, processing delay, and offline lead-time interpretation. Astra fits the system-wide profiling and code work; Extra High is justified by incremental before/after attribution, regression tolerances, causality/parity checks, and safe rollback decisions. |
| [Phase 17](../phases/phase-17-testing-hardening.md) | Verification / Reliability Engineering | GPT-6 Astra | Extra High | Fault injection spans tracking, capture timing, model fallback, audio loss, background motion, and DEGRADED commits, while invariant and soak suites must protect the complete system. Astra fits the broad debugging work; Extra High is justified by cross-component failure-mode analysis and evidence that recovery never fabricates strikes or violates causality. |
| [Phase 18](../phases/phase-18-evaluation-experiments.md) | Experimental ML / Evaluation | GPT-6 Astra | Extra High | The final pre-registered comparison combines participant-level offline analysis, counterbalanced live blocks, external synchronization, uncertainty estimates, and reproducibility. Astra fits the scientific and systems workload; Extra High is justified by causal evaluation, leakage control, and precise separation of measured action-to-sound latency from software estimates. |
| [Phase 19](../phases/phase-19-ablation-study.md) | Experimental ML / Ablation Analysis | GPT-6 Astra | Extra High | One-factor ablations change feature groups, history, horizons, trajectory structure, tip method, and frame rate under frozen folds, seeds, and operating rules. Astra fits the research workflow; Extra High is justified by confounding and leakage risks, matched participant analysis, conditional feasibility, and interpretation of null or adverse results. |
| [Phase 20](../phases/phase-20-final-integration.md) | Systems Integration / ML Engineering | GPT-6 Astra | Extra High | The release candidate freezes model/configuration hashes and combines all arms, calibration, dashboard, hardening, presets, and the full regression suite. Astra fits the large autonomous integration; Extra High is justified by cross-phase dependency tracing and proving the shipped behavior still matches the evaluated system. |
| [Phase 21](../phases/phase-21-documentation-thesis.md) | Technical Documentation / Research Synthesis | GPT-6 Astra | High | Thesis chapters, generated figures, claims audit, requirements coverage, and reproducibility instructions must agree with manifests, gate records, and measured limitations. Astra fits the broad research synthesis; High is sufficient because this phase traces and reviews established evidence rather than designing a new model or experiment. |
| [Phase 22](../phases/phase-22-graduation-demo.md) | Demo Engineering / Reliability | GPT-6 Sol | High | The demo prepares a script, venue pre-flight, calibrated presets, fallback drills, rehearsals, and evidence slides from the accepted release candidate. Sol fits this bounded integration and presentation work; High covers runtime contingency planning and checking every spoken or shown claim against the thesis audit. |
| [Phase 23](../phases/phase-23-final-packaging.md) | Release Engineering / Reproducibility | GPT-6 Sol | High | Packaging verifies the accepted bundle, archive manifests, checksums, installation, licences, consent-scoped dataset decision, and final status table. Sol fits these specified release checks; High covers artifact integrity and evidence traceability, while owner and institutional decisions remain explicit gate inputs. |

Phase 12 remains optional under its existing entry decision and go/no-go rules. Its recommendation applies if extensions are attempted.

These are project workload judgments, not claims that one model is universally superior. Official OpenAI guidance describes Astra as suited to demanding analysis and complex deliverables, and Sol as suited to writing, coding, and work requiring judgment. Both High and Extra High (API value `xhigh`) are supported for the selected models. [Official model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection), [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol).
