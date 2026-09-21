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

Every listed file carries its byte size and SHA-256; `manifest_hash` (canonical SHA-256 of the manifest) is the
`dataset_hash` of experiment logs. `scripts/build_raw_manifest.py check <manifest>` re-hashes every file.
