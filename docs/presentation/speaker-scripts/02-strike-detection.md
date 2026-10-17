# Strike Detection and Motion Analysis

Slide 7. Target: 80–90 seconds. Purpose: explain movement, zone selection and duplicate control. Show `assets/strike-pipeline.png`, also editable on the slide.

## Spoken script

“My role is to explain when motion should produce one drum event. A point being inside a pad is not enough by itself.

The product pipeline uses MeasuredStrokeGeometry. It compares recent accepted positions and checks downward speed, direction and minimum travel. It then checks whether the movement crosses a drum's top edge. If several edges are crossed during one movement, the earliest eligible crossing wins.

After a candidate exists, the commit policy checks tracking status, dropped frames, the current strike episode and short refractory timers. Rebound allows the next stroke. This helps prevent repeated sounds while a tip stays inside a pad.

There is an important demo setting. The fixed-guide configuration enables thirty-three milliseconds of edge look-ahead after sustained downward motion. A stroke stopping just above an edge may therefore trigger. Normal product geometry defaults to an observed crossing.

Target selection still needs independent validation. A movement through an upper pad before reaching a lower pad can select the upper one. Missing tips can also prevent a valid strike.

Our next work is to compare intended, time-labeled strokes with commits, including rolls, wrong-zone events and deliberate non-strike movement. We need trustworthy points from computer vision and stable timing from the core.

The frontend presenter will show how these events appear on screen.”

## Likely questions

- **Do you use force?** No. Downward motion supplies a kinematic intensity proxy for gain.
- **Can two hands strike together?** The pipeline keeps separate per-hand state and event IDs, and the mixer supports overlapping voices. Real simultaneous-hit accuracy still needs testing.
- **What failed in the fresh suite?** The synthetic full-kit ordering test produced tom2 where snare was expected. It failed again alone; we have not diagnosed or fixed the cause during this audit.
- **What is the measured wrong-zone rate?** No accepted independent live rate exists yet.
- **Why can a lower drum be missed?** The first eligible edge can consume an uninterrupted downstroke; lower pads should be approached from the row gap.

Evidence: `geometry/strokes.py:MeasuredStrokeGeometry.observe`, `commit/policy.py:PerHandCommitPolicy.step`, `configs/product.candidate.yaml`, `configs/demo.professor.candidate.yaml`. Acceptance: publish a confusion matrix and missed/false/duplicate event counts against independent truth; do not substitute synthetic pass rates.
