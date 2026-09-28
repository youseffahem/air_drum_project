# ADR-0043 — Phase 19 preparation and per-arm live settings

Date: 2026-09-27. Status: engineering preparation; experimental execution PENDING.

The owner permits Phase 19 preparation while Phase 18 remains PENDING. This does not
approve either preregistration or accept a phase gate.

1. Add an offline `spacedrums.ablation` layer above `live_eval` and the frozen Phase 09
   harness. It reuses existing normalization, windows, training, export, replay,
   participant metrics and bootstrap functions. No causal stage imports ablation code.
2. Keep feature dimension/architecture fixed for masks; zero values and validity flags
   after normalization in both training and replay. Remove explicit redundant cues
   listed in the draft protocol. Keep all label access outside causal transformations.
3. The CLI provides generated SYNTHETIC/DEV runs, read-only dependency checks and stored
   report regeneration. `--execute` always refuses during this authorization. Synthetic
   mode accepts no dataset, model, session or frozen-reference path overrides.
4. A future real reference must bind all inputs, reviewed CV sessions, protocol approvals,
   gate decision, W/delay and reference results. Missing files, hash drift, cross-fold
   identities, reserved test access or synthetic substitution fail closed. No invented
   reference or ds-v1.0 is supplied.
5. Implement the offline portion of ADR-0036: config schema 1.9 optionally carries complete
   A/B/C commit settings, per-arm v_min and B's full independent rule settings. Older
   configurations keep their existing shared settings. Separate geometry instances retain
   arm-specific thresholds and candidate identities. Switching/fallback preserves suppression.
   The auditor uses each originating arm's settings and refractory deadlines across switches.
6. Live locks require pinned live and offline configs and an archived offline lock from the
   same preregistration/evidence class. Live settings must equal the offline reference after
   the same defaults/overrides are resolved. New offline source freezes include the exact
   base configuration bytes. This closes the formerly implicit base-config dependency.
7. The candidate live config is development material. Its B horizon is independent of C's;
   its values are not represented as locked or selected. C-MT/extension adoption and all
   real live settings verification remain PENDING. The sticky fallback policy is unchanged.

Tests and evidence pointers are in the Phase 19 preparation report. No Phase 18 experimental
results, preregistration document or approval/hash ledger are changed by this preparation.
