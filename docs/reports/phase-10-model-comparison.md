# Phase 10 model-family comparison

Status: PENDING participant comparison and model-selection ADR.

No winner is selected. A, B CV/CA, C-GBDT direct/trajectory, GRU and TCN must compete
under identical participant splits, matching W, geometry/commit policy and delay
definitions. A simpler arm may win. The tested selector filters achieved points
by FP/FN/timing/CPU bounds before maximizing lead, with deterministic tie-breaking.

The development comparison tool uses the Phase 08 synthetic fixture at candidate
N8/K4. It converts only GBDT target tensors onto the temporal model's fixed
1/30s grid, preserving X/M, fold statistics and participant-group assignments.
Baseline model implementations and the Phase 09 evaluator remain unchanged.
Both C-GBDT modes and both B motion models are exercised. This is tooling
verification, not a validation-selected operating-point or participant comparison.

Full research reporting still needs per-participant median/IQR/positive-fraction
lead, FP/min and FP fraction, FN, timing MAE/bias, zone accuracy, ADE/FDE with
support, impact-position and intensity (Pearson/Spearman/MAE), complete inference
latency and memory/resource tables, seed variance and paired participant-bootstrap
differences. Existing Phase 09 metrics provide the main event fields; complete
participant comparison extensions remain pending with those inputs. Parameter
storage is not peak process memory. Synthetic identifiers are never counted as
real participants.

The temporal MODEL wrapper uses inward crossing speed as requested. Existing
baseline geometry uses crossing-speed magnitude for intensity; that distinction
must be reported and harmonized as a comparison diagnostic without changing the
frozen geometry's event rules. See ADR-0027.

Outcome interpretation remains open: temporal model better, no material
difference, or baseline better. No clean-model reproduction, effect on physical
sound timing, or effective-latency reduction has been demonstrated.

## Completed synthetic diagnostic

Run `experiments/phase-10/20260924-2001-synthetic-comparison/run.json`
completed with 529 hashed artifacts and 363 operating-point/session evaluations.
It includes nine GBDT fits (three seeds per fixture fold) and the 18 N8/K4
temporal fits from the horizon run. All use candidate W=.05s and zero replay
processing delay; neither value is a frozen participant analysis decision.

| Arm | Evaluations | Evaluations with any match | FP/min range | FN-rate range |
|---|---:|---:|---:|---:|
| A | 3 | 0 | 0 | 1 |
| B CV | 18 | 0 | 0 | 1 |
| B CA | 18 | 0 | 0 | 1 |
| C-GBDT direct | 54 | 18 | 0–344.73 | 0–1 |
| C-GBDT trajectory | 54 | 0 | 0 | 1 |
| GRU | 108 | 48 | 0–792.88 | 0–1 |
| TCN | 108 | 17 | 0–344.73 | 0.667–1 |

These ranges span different settings/seeds/synthetic sessions; they are not
confidence intervals or a ranking. A, both B variants and C-GBDT trajectory
produced no matched events in this fixture. Their lead is undefined, so they
are absent from `lead-vs-fp.png`, but retained with null lead and FN=1 in
`curves.json`. The scripted fixture does not supply a realistic baseline
comparison. No superiority claim follows from these outcomes. The figure was
visually inspected; full event tables and grouped bootstrap diagnostics are
archived, with the participant limitations above unchanged.
