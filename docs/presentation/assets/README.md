# Visual evidence index

All photographic content comes from existing local developer recordings or genuine application windows processing those recordings. No screenshot, tracking point, success state or person was generated. No new webcam recording was needed. Images were visually checked for irrelevant desktop content, credentials and personal paths; the captures show only the application window. Camera scenes retain context necessary to understand tracking. These are local presentation materials, not permission for public distribution of a person's image.

| Filename | What it demonstrates | Origin and type | Limits |
|---|---|---|---|
| `hand-replay-window.jpg` | Current seven-piece kit and mirrored preview | Genuine application-window screenshot captured 17 Oct 2026; `app.play --demo --fingers --replay data/dev-product/dev-product-20261017-005812-ccdb76de --no-audio` | Recorded frames, fixed guide, audio disabled; no new live/bare-hand validation |
| `hand-diagnostics-window.jpg` | Accepted index fingertip, missing other tip and top-edge guides | Same running HAND replay, D diagnostics | On-screen timings collected during concurrent audit activity; not benchmark evidence |
| `stick-diagnostics-window.jpg` | Red mask, NO TIP/weak-limit state and NO_MEASURED_TIP stroke reasons | Genuine application-window screenshot; same recording through `--demo --red-tips --no-audio`, D diagnostics | Default red settings, recorded replay; demonstrates failure rather than successful hits |
| `recorded-camera-frame-140.png` | Raw camera image with painted sticks at playing position | Byte-for-byte copy of `data/dev-product/dev-product-20261017-005812-ccdb76de/frames/frame_000140.png`; recorded frame | Raw 640×480 tracking image, no overlay and no success claim |
| `recorded-four-pad-preview.png` | Earlier four-pad developer guide and visible endpoints | Copy of `experiments/developer-demo-software/RECORDED-demo-preview.png`; pre-existing recorded-frame preview | Already labeled RECORDED IMAGE / preview only; not the current default kit or new live screenshot |
| `red-tip-default-contact-sheet.jpg` | Default detector losses, rejects and misplaced associations across 12 frames | Copy of `experiments/red-tip-lit/contact-sheet.jpg`; existing offline diagnostic image from the 572-frame session | “lit” is the folder name, not proof of successful lighting; no ground-truth labels |
| `red-tip-dark-contact-sheet.jpg` | Optional dark-mode measurements on the same footage | Copy of `experiments/red-tip-dark/contact-sheet.jpg`; existing offline diagnostic image | More accepted points does not establish correct cap tracking |
| `architecture.png` | Camera, vision, tracking, geometry, commits, audio and observation paths | Source-grounded diagram, exported from slide 4; native editable shapes in PPTX | Explanation of implementation, not a runtime screenshot |
| `strike-pipeline.png` | Measurement, motion, edge, commit and event stages | Source-grounded diagram, exported from slide 7 | Demo look-ahead limitation stated; no synthetic motion represented as recorded truth |
| `core-contracts.png` | Typed records exchanged by local components | Source-grounded diagram, exported from slide 9 | No network service or mobile interface implied |
| `audio-pipeline.png` | Zone/sample mapping, selection, scheduler and mixer | Source-grounded diagram, exported from slide 10 | Describes playback architecture; does not measure physical latency |

Diagram source locations and function names are in slide speaker notes and `../project-audit.md`. All 15 slide renders are in `../previews/`. Their contents include genuine evidence, native diagrams and presentation text; they are not additional application screenshots. Source/output hashes are recorded in `../evidence/asset-provenance.json`.

## Uncollected evidence

- New live webcam HAND/STICK performance: no physical player trial conducted during this audit. Existing recordings and running replays were sufficient for a safe presentation.
- Reliable all-zone hits, calibration acceptance, audibility and physical latency: not established; no fake substitute included.
- Mobile screenshots: unavailable because no verified app exists.
- A prerecorded successful-play video/audio clip: not verified and not included. The supplied still images and embedded diagrams remain the presentation-safe fallback.
