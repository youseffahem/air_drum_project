# configs/

**Status:** schema IMPLEMENTED (Phase 01, Task 01.7); no runnable profile exists.

- `schema/config.schema.json` - the top-level configuration schema (ADR-0010). Every resolved config is validated against it before a run starts (docs/reproducibility-policy.md section 3).
- `example.candidate.yaml` - schema example and test fixture. **Every number in it is a candidate placeholder**; it is not a runnable or tuned profile.

Naming (docs/repo-layout.md section 3.1, amended by ADR-0010): frozen, citable configs are `<component>.<variant>.v<N>.yaml` with `meta.status: frozen`; development files are `*.candidate.yaml` with `meta.status: candidate` and may not be cited by a gate record or result. The first real profiles arrive with Phase 02 (camera) and Phase 04 (zones, audio).
