# Validation results

17 October 2026. These results apply to the existing working tree at `188b4e3`, including the user's uncommitted changes. No application behavior was changed.

## Software checks

| Check | Result | Scope and limitation |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest -ra` | **1 failed, 1,997 passed, 1 skipped, 139 warnings; 1,020.06 s** | Full configured suite. Passing tests are software evidence, not real-world accuracy. |
| Focused full-kit test rerun with `-vv --tb=long` | **1 failed in 4.63 s** | Reproduces the ordering failure without the rest of the suite. |
| `.venv\Scripts\python.exe -m ruff check . --output-format concise` | **1 E501** | Existing `src/spacedrums/stick/visible.py:245`, 113 characters vs 110. No autofix. `.venv`, `data`, `experiments` excluded by config. |
| `.venv\Scripts\lint-imports.exe --no-cache` | **7 contracts kept, 0 broken** | 198 files / 564 dependencies. Two declared features-to-geometry type imports are intentionally ignored. |
| HAND and red-tip developer `--check` | **HASH_VERIFIED** | Hand-model and acoustic sample assets. `camera_opened=false`, `audio_opened=false`, `live_verified=false`. |
| Genuine application replay | **HAND and red-tip windows captured** | Existing 572-frame session, fixed developer guide, audio disabled. No fresh physical trial or performance benchmark. |

The failed test is `tests/product/test_full_kit.py::test_a_run_around_the_kit_sounds_each_piece_in_order`, assertion at line 99. Expected zone order is crash, tom1, tom2, ride, hihat, snare, floor_tom. At index 5, the actual committed zone is tom2 rather than snare. The test supplies synthetic swings and checks commit order. Its name does not establish that a listener heard each piece. The root cause was not diagnosed or fixed as part of this presentation task. It is included in slide 12, the audit, responsibility map and scripts.

The skipped hardware test is `tests/capture/test_hardware_capture.py:28`; `SPACEDRUMS_HW_TESTS` was not enabled. Warnings include TorchScript deprecations, deprecated `jsonschema.__version__` access and a requires-grad tensor scalar conversion. Full output is retained under `evidence/`.

## Presentation and content checks

- Final file contains **15 slides**, with all six requested roles and seven script files including the leader's opening/closing. The leader is one of the six presenters.
- All 15 slides were rendered at 1280×720 and inspected individually. Crowded text and reversed arrows found in the first draft were corrected. Changed slides were rendered and checked again. Images use proportional contain placement; the evidence remains readable and unstretched.
- Package integrity: **pass, zero findings**. Layout/heading/native-table geometry: **pass, zero findings or warnings**. Arial font policy passed. Native editable tables are on slides 5 and 12; process diagrams use native shapes/connectors. Screenshots are embedded.
- The final PPTX **reopened successfully through the first-party presentation library**, with 15 slides. This verifies file parsing, not desktop PowerPoint rendering. The finalizer receipt and SHA-256 are in `evidence/presentation-validation.json`.
- **Desktop PowerPoint was not opened or inspected.** Computer Use was stopped with the Escape key, and no further application-window control was attempted. Open the file in slideshow mode on the presentation computer before the event. PNG previews are supplied as a fallback.
- Claims were cross-checked against source, developer records and fresh checks. Mobile remains explicitly unimplemented with unresolved scope. Tracking coverage is separated from accuracy. Software compute and audio buffer duration are separated from physical action-to-sound latency. The observed test failure is disclosed.
- Speaker passages total approximately **1,591 words**. At roughly 145 words/minute, the planned 11 minutes of speech plus about 20 seconds of transitions is realistic. Actual delivery must be timed during rehearsal. Q&A is separate; a short optional demo fits only if the complete rehearsal stays under 12 minutes.
- Explicit file references were checked; source subpaths such as `app/play.py` resolve under `src/spacedrums/`. Generic session filenames are contextual, not separate missing deliverables. Image hashes and origins are recorded in `evidence/asset-provenance.json`.
- Screenshots show application windows or the recorded camera scene, with no unrelated desktop, credentials or personal directory paths observed. Copied textual evidence replaces personal root directories with `<repo>` or `<user>`; this redaction does not change measurements. A pattern scan of authored text and PPTX XML supplements the visual check; it is not a guarantee against every possible secret format.

## Preservation and unresolved inputs

SHA-256 comparison of **876 pre-existing tracked/nonignored files found zero changes or missing files**. HEAD and Git status outside `docs/presentation/` match the initial snapshot: 20 already-modified tracked files and 34 pre-existing untracked entries. No commit, push, reset or clean was performed. New private build/replay outputs are under ignored `experiments/presentation-build/`; ordinary test caches may have changed. The original recordings and photographic source files were not edited.

Still needed from the team: verified member names, institution/supervisor if required, final instructor timing, assignment of the leader duty and an explicit mobile-scope decision. Still needed from future engineering work: diagnosis/fix of the synthetic kit-order failure, independent tracking/strike truth, calibration acceptance and physical audio timing. These are limitations of the project, not missing invented content in the presentation.

See `MANIFEST.md` for every delivered file and `project-audit.md` for detailed conditions and prohibited claims.
