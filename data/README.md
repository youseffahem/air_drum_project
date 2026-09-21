# data/

**Git-ignored.** Recordings and datasets live here on the development machine only.

Layout (from Phase 06/07): `data/ds-raw-v<M>.<m>/`, `data/ds-v<M>.<m>/`, each with a `manifest.json` (SHA-256 per file).
Only manifests and dataset cards are ever committed. No content may exist here before Phase 06 (Phase 00 rule: no dataset directories with content).

`data/dev-captures/` (Phase 02/03) and `data/dev-sessions/` (Phase 05: prototype sessions recorded by `spacedrums.app.main --record`, developer only — currently replays of the existing dev captures, `dev-p05-swing-L2-exp-*`) are developer-only material, git-ignored, never a dataset and never participant data.
