# data/

**Git-ignored** except `README.md` files and `data/manifests/` (manifests + exclusion logs, Phase 06). Recordings and
datasets live here on the development machine only.

Layout (Phase 06, ADR-0019): `data/raw/<participant_id>/<session_id>/` (frames PNG sequence, `frames.jsonl`,
`records/`, `timing.jsonl`, `config.snapshot.yaml`, `session.json`, `metadata.json`, `verify.json`, `checklist.json?`,
`audio_track.wav?`); `data/manifests/<dataset_version>.json` (+ `.exclusions.jsonl`) with SHA-256 per file. Phase 07:
`data/ds-v<M>.<m>/` (labels, splits). Only manifests and dataset cards are ever committed.

**No participant data exists** (Phase 06 gate: campaign PENDING). `data/raw/DEV/` may hold DEV CAPTURE ingest
sessions (re-processed Phase 02 developer captures; never participant data, never a dataset).

`data/dev-captures/` (Phase 02/03) and `data/dev-sessions/` (Phase 05: prototype sessions recorded by
`spacedrums.app.main --record`, developer only — replays of the existing dev captures, `dev-p05-swing-L2-exp-*`)
are developer-only material, git-ignored, never a dataset and never participant data.
