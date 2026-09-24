# ADR-0026 — Phase 10 horizon and temporal contract

Status: PENDING empirical horizon selection; implementation contract tested.
Date: 2026-09-24.

K/H is chosen from the predeclared lead/FP/FN/timing/CPU feasibility rule, not minimum
trajectory loss. Candidate synthetic grids exercise K=1,2,4 at dt=1/30s. There is
no selected research horizon. The history/auxiliary developer sweep uses candidate
K=4 only to exercise machinery; it does not claim the dependent CV decision exists.

Phase 08 targets are delivered-frame samples with actual offsets, whereas Phase
10's head predicts on a fixed clock. Resample only contiguous target spans with
the current tip as the zero-displacement anchor, masking unsupported tail points.
Keep actual input dt and window_elapsed. This target transform is offline only.
Prediction offsets remain fixed independently of a live frame interval; live
input resampling/integration remains Phase 13.

An ordinary ever-carried GRU state cannot satisfy exact rolling-N truncation.
The implementation carries one recurrent state per surviving start, bounded by N,
and returns the oldest lane. Rebuild when overlapping normalized features change
(notably window_elapsed). This costs O(N) recurrent work and does not promise an
O(1) speedup. Report both windowed and cache timings with rebuild counts.

Both encoders truncate to N. GRU is unidirectional; TCN has only left padding and
no temporal normalization. TCN receptive field is checked against N. INVALID/STALE
reset per-hand model state; the upstream feature assembler retains Phase 08 mask/dt
semantics. Adapter warm-up requires N live states. No weights are selected here.
