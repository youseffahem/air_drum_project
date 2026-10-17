# Backend and Core Processing

Slide 9. Target: 80–90 seconds. Purpose: explain local orchestration and contracts. Show `assets/core-contracts.png`, also editable in the slide.

## Spoken script

“My role is to explain the core processing. Here, backend means the local Python pipeline. There is no cloud server or mobile API in the current project.

The play runner loads and validates configuration, starts capture and perception, and owns shutdown and reporting. The capture source uses a bounded queue so slow processing does not create an unlimited backlog. It records dropped frames and timing.

Components exchange typed records. A frame has an identity and timestamps. Perception produces hand and stick observations. Tracking produces a TrackState. Geometry produces a StrikeCandidate, and the commit policy may turn it into a CommittedStrike. Audio then records an AudioEvent.

The pipeline checks that observations belong to the current frame and hand. Each hand keeps separate state. Tracking resets also reset its strike history.

Replay lets us process saved frames through the application without opening a camera. That is how we collected the presentation screenshots. The current playable product uses measured Arm A only. The broader research runner has rule and model alternatives, with separate validation needs.

Our next work is repeatable integration testing and clear setup documentation. We also need to reconcile older documentation with current defaults.

The audio presenter will now follow a committed event to its sound.”

## Likely questions

- **Do you process every camera frame?** No guarantee. A bounded queue can drop old frames, and drops are logged.
- **Is the whole program one thread?** The frame decision loop is inline, with a capture thread and an audio callback path.
- **Does replay prove live latency?** No. Replay verifies processing behavior under recorded input; hardware and acoustic timing differ.
- **What protects architecture boundaries?** Seven import-linter contracts passed; two zone-type import exceptions are explicitly configured.

Evidence: `app/play.py:run`, `app/pipeline.py:DecisionPipeline.step`, `capture/source.py:LiveFrameSource`, `contracts/records.py`, `.importlinter`. Dependencies: all six roles need agreed contracts; mobile integration needs a new scope/interface decision. Acceptance: reproducible clean setup, current-frame causality, correct failure behavior and traceable logs.
