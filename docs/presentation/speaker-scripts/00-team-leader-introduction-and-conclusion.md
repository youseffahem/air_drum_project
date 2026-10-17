# Team leader: opening, results and closing

Assign this duty to one of the six role presenters, preferably the core-processing presenter. No additional team member is implied. Role scripts describe team responsibilities, not personal authorship. Target: opening 90 seconds; results/closing 70 seconds, plus transitions. Rehearse with a timer.

## Opening: slides 1–5

“Good morning. Our project is SpaceDrums, a camera-based AI virtual drumming system. We are presenting the current prototype and the evidence behind it.

A physical drum kit needs equipment and space. Our goal is to let one person explore drumming using a camera, virtual drum zones and local sounds. We also want to investigate whether motion prediction can reduce delay. That research question is still open.

The prototype already captures camera frames, estimates hand or stick-tip positions, identifies candidate strikes and schedules drum samples. It also provides a desktop kit display and diagnostic logs. Reliable play across lighting conditions and complete physical latency measurement still need work.

The architecture slide shows the actual path through the code. Camera frames feed perception. Per-hand tracking and drum geometry produce strike candidates. Commit rules decide which events can reach audio. The interface displays those results.

We organize the project into six responsibilities: computer vision, strike detection, frontend, core processing, mobile planning and audio. Mobile implementation and approved scope remain unresolved.

Python and OpenCV connect the local system. MediaPipe supports hand detection. NumPy supports geometry, and sounddevice supports playback. PyTorch and LightGBM belong to the research tools. Our current product demo uses measured Arm A, not a validated learned prediction model.

Our computer-vision presenter will now explain the input modes.”

Show `assets/architecture.png` on slide 4. The same diagram is editable in the deck.

## Results and closing: slides 12–15

“Our results separate software tests from real recordings. The suite passed 1,997 tests, failed one and skipped one. The failed synthetic kit sequence produced tom2 where snare was expected; it failed again on its own. Seven import contracts passed, while lint found one long line. These checks do not measure real-world tracking accuracy.

On one 572-frame recording, default red-tip tracking produced measured points in only 6.8 percent of left-slot frames and 1.6 percent of right-slot frames. Dark mode raised coverage, but this recording has no accuracy labels. We cannot call those percentages correct detections.

The main challenges are lighting, identity during occlusion, reliable calibration, intended-zone selection and physical audio delay. Our next step is independent labeling, followed by controlled tracking and strike tests. We will then validate calibration and measure action-to-sound latency with an external reference. Mobile scope needs an explicit decision.

SpaceDrums demonstrates a connected camera-to-sound software prototype. Its strongest next step is reliable, measurable interaction. Thank you. We welcome your questions.”

## Likely questions

- **Is the project finished?** The integrated prototype and research machinery exist. Independent playing validation, participant results and release acceptance remain pending.
- **Did each person write the code for their role?** This presentation maps responsibilities. Individual authorship has not been verified.
- **Why are there no names or institution on the title?** They were not provided or verified. Add the agreed details before submission.
- **Why show failures?** They identify the actual work remaining and prevent synthetic or software evidence from becoming unsupported user-performance claims.
