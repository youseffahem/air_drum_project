# Phase 10 held-out participant evaluation

Status: PENDING. **No test-participant run has been executed.**

Task 10.13 requires the Phase 09 gate/frozen W, reviewed ds-v1.0 folds, CV evidence,
an owner-approved FP budget, timing/FN/CPU bounds, selected H/N/family, all arms'
operating points, and a hashed pre-registration archived before access. These are
absent. The current eval CLI rejects test mode before opening inputs; this is tested.

Do not mistake fixture grouping keys containing `SYNTHETIC` or their held-out
fixture identity for research participants. Training uses train/val archives only.
No task in this phase creates consent, recordings, reviewed participant labels,
or a dataset freeze. No exploratory participant test analysis has run either.

Once the prerequisites exist, the reviewer must authorize the completed frozen
protocol and single-run ledger. Implement/verify that protocol-specific runner,
then run each predeclared operating point once for A, B CV/CA, C-GBDT both modes and
the selected temporal arm(s). Fill the full per-participant metric/CI tables here.
Additional test analyses are exploratory and cannot support retuned confirmation.

Task 10.14's selected-model clean/independent reproduction consequently remains
PENDING. Development checkpoints, exports, hashes, raw logs and reloaded metric
checks exist separately; none is labelled VALIDATED.
