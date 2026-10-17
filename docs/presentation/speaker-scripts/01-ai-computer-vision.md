# AI and Computer Vision

Slide 6. Target: 80–90 seconds. Purpose: explain where accepted position measurements come from. Show `assets/hand-diagnostics-window.jpg`; point to the measured fingertip and the missing second tip. The image is a current application screenshot using recorded stick footage, not a new bare-hand trial.

## Spoken script

“My role is to explain the computer-vision part of the system. It must give the rest of the pipeline a position supported by the current frame.

SpaceDrums has different input paths. HAND mode uses MediaPipe hand landmarks. The fingertip estimator takes landmark eight as the index fingertip and landmark five as its origin. The diagnostic screenshot shows one accepted point and one missing tip. It was captured from recorded footage with audio disabled.

Visible-stick mode instead searches for image support along a hand-guided stick axis. Red-tip STICK mode uses color segmentation and temporal association for painted caps. It does not run the hand model by default. Painted tips are explicitly a marker condition.

The red-tip tracker can report observed, weak, dark, ambiguous or missing evidence. Predicted positions help association but do not become measured strike points. The confidence values are configured evidence classes, not accuracy percentages.

The main problem is reliable detection at playing distance. Dim paint, motion blur and objects with similar colors cause losses or wrong associations. Our next work is to label both real tips on separate evaluation recordings and measure errors and identity swaps.

The strike-detection presenter will explain how accepted points become drum events.”

## Questions and evidence

- **Is red-tip tracking AI?** It is conventional computer vision with color segmentation and temporal association. HAND uses a pretrained MediaPipe model; temporal neural predictors are separate research code.
- **Why not keep predicting through a loss?** The current product requires measured endpoint evidence for strikes, to avoid inventing hits.
- **Does 0.9 confidence mean 90% accuracy?** No. It is a configured evidence class.
- **What proves the implementation?** `app/red_tip_perception.py:RedTipPerception`, `stick/red_tip_estimator.py:_emit`, `stick/visible.py:FingertipEndpointEstimator.estimate`, and the replay logs.

Next-step dependency: core must preserve frame identity and timestamps; strike analysis must connect each missed event to its measurement history. Acceptance needs independently labeled positions and predeclared metrics.
