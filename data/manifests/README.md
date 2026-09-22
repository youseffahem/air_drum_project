# data/manifests/

**Tracked in git** (the only content under `data/` besides `README.md` files). One manifest per raw dataset
version (Phase 06, Task 06.9; ADR-0019; `schemas/raw-manifest.schema.json`):

- `ds-raw-v<M>.<m>.json` — PARTICIPANT sessions with SIGNED consent only. **None exists: no participant has been
  recorded (Task 06.11 PENDING).** `scripts/build_raw_manifest.py build ds-raw-v1.0` refuses to write an empty
  participant manifest.
- `ds-raw-v<M>.<m>-pilot.json` — PILOT sessions with SIGNED consent. **None exists (Task 06.10 PENDING).**
- `ds-raw-v0.0-selftest[-<slug>].json` — SYNTHETIC / DEV CAPTURE sessions only, labelled TEST / DEVELOPMENT ONLY.
  Produced by the Phase 06 self-tests into temporary directories; not kept here, so that nothing under this
  directory can be mistaken for a dataset.
- `<version>.exclusions.jsonl` — the `ExclusionRecord`s of the sessions a manifest considered (unusable-recording
  policy, `docs/policies/unusable-recording-policy.md`).

Phase 07 adds the **labelled**-dataset manifests (`schemas/dataset-manifest.schema.json`,
`scripts/build_dataset_manifest.py`), with the same kind gating:

- `ds-v<M>.<m>.json` — PARTICIPANT labelled dataset. **None exists**, and an empty one is refused.
- `ds-v<M>.<m>-pilot.json` — PILOT labelled dataset. **None exists.**
- `ds-v0.0-selftest[-<slug>].json` — SYNTHETIC / DEV CAPTURE label sets only, labelled TEST / DEVELOPMENT ONLY.
  These are development artefacts and are **git-ignored** (`.gitignore`: `data/manifests/*selftest*`), so that
  nothing under this directory can be mistaken for a dataset.

A labelled manifest additionally pins the label machinery (`machinery`: rules version and hash, thresholds hash,
smoother id and hash, tracker id and hash, geometry version, zone layout, `v_min`, interpolation). **Every listed
label set must share that `labels_hash`**; one produced by different rules, thresholds, smoother or tracker is
listed under `refused` with the reason, never silently mixed. Versioning rule: a change to the machinery produces a
new `labels_version`; a change to the accepted sessions produces a new `ds` minor version.

Every listed file carries its byte size and SHA-256; `manifest_hash` (canonical SHA-256 of the manifest) is the
`dataset_hash` of experiment logs. `scripts/build_raw_manifest.py check <manifest>` and
`scripts/build_dataset_manifest.py check <manifest>` re-hash every file.
