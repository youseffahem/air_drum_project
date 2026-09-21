# configs/

**Status:** schema 1.2 IMPLEMENTED (Phase 01 schema, Phase 02 minor bump — ADR-0013, Phase 03 minor bump — ADR-0014/0015: optional `hands` and `stick` blocks); one camera fragment exists; no frozen profile yet (Phase 02 C-5 stays open: ADR-0017).

- `schema/config.schema.json` — the top-level configuration schema (ADR-0010). Every resolved config is validated against it before a run starts (`spacedrums.config`, docs/reproducibility-policy.md section 3).
- `example.candidate.yaml` — schema example and test fixture (a 1.2 document since Phase 03; every number a candidate placeholder). Also the **base document** onto which fragments are merged; it carries the `hands` and `stick` blocks that `spacedrums.hands` / `spacedrums.stick` read and a real `tracking.filter` (`kalman_cv`, ADR-0016).
- `camera/hw01-integrated-webcam.candidate.yaml` — Phase 02 camera fragment (`meta` + `camera_profile` + `roi`) for HW-01; candidate values, measured fields null until cited runs exist (docs/camera-profile-hw01-integrated-webcam.md).

Naming (docs/repo-layout.md section 3.1, ADR-0010): frozen, citable configs are `<component>.<variant>.v<N>.yaml` with `meta.status: frozen`; development files are `*.candidate.yaml` with `meta.status: candidate` and may not be cited by a gate record or result. Fragments: a file may carry only the blocks it owns plus `meta`; the loader merges fragments onto a base and validates the whole. A fragment's `meta.schema_version` is the version of the merged document it forms (its `meta` wins the merge), so the HW-01 fragment declares 1.2 although its own blocks are 1.1 content (ADR-0014).
