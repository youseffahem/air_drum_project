# Space Drums — Project Discovery & Requirements

> This document contains the confirmed project requirements and decisions provided by the project owner.
> It should be treated as a primary requirements source when designing the architecture, implementation roadmap, dataset, AI system, and experiments.

---

## A — Project Vision & Purpose

### 1. What is Space Drums in one clear paragraph?

**Answer:**

Space Drums is a software-only virtual/air drumming system that uses a single webcam and Computer Vision to track ordinary drumsticks held by the user. The system estimates the motion of the stick tip, detects or predicts imminent virtual drum strikes, maps them to virtual drum zones, and plays the corresponding drum sounds in real time. The main research contribution is Causal Temporal Strike Anticipation rather than simple motion detection.

---

### 2. What is the main problem Space Drums is trying to solve?

**Answer:**

The project aims to allow users to play a virtual drum kit without owning or using a real electronic drum kit. From the research perspective, the project focuses on reducing perceived Action-to-Sound Latency by predicting an imminent strike before the actual/virtual impact occurs.

---

### 3. Who is the primary target user?

**Answer:**

The primary user is someone who wants to interact with a virtual drum kit using ordinary drumsticks and a webcam, especially beginners, students, hobbyists, and users who do not have access to a real drum kit.

---

### 4. What should happen from the moment the user launches the system until they hear the first drum sound?

**Answer:**

The system should provide a dedicated area on the webcam screen where the user is instructed to stand so that the camera setup is appropriate. The system then detects and tracks the user's hands and drumsticks. Virtual drum zones appear on the screen. The user moves a drumstick toward one of the virtual zones, the system estimates/predicts the strike, commits the event, schedules the appropriate sound, and plays the corresponding drum sound.

---

### 5. What is the main research contribution?

**Answer:**

The main contribution should be causal temporal prediction for anticipating drum strikes using hand/stick motion data extracted from the camera. The project should clearly measure Prediction Lead Time, Timing Error, False Positives, and the effect of prediction on Effective System Latency.

---

### 6. Is Space Drums primarily a research project, a usable product, or both?

**Answer:**

Both. However, the research side is the primary graduation-project contribution. At the same time, the system should be usable enough to demonstrate a real-time virtual drumming experience.

---

# B — Drumming Experience

### 7. Does the user need to hold two physical drumsticks?

**Answer:**

Yes. The intended interaction uses two ordinary drumsticks without any electronic sensors attached to them.

---

### 8. Do the drumsticks need to contain any special hardware?

**Answer:**

No. The goal is to use ordinary drumsticks without IMUs, ESP32 modules, or any other electronic hardware.

---

### 9. Will the drumsticks use visual markers?

**Answer:**

The primary goal is Markerless Tracking. Colored tape or visual markers may only be used as a fallback solution or as a benchmark condition if Markerless Tracking proves unreliable.

---

### 10. Which is more important to track: the hands or the sticks?

**Answer:**

Both are very important because the system needs to understand the movement quickly enough to predict the upcoming strike.

---

### 11. Can either hand hit any virtual drum zone?

**Answer:**

Yes. Unless future experiments show that assigning specific zones to specific hands improves reliability, either hand should initially be able to interact with any virtual drum zone.

---

### 12. What types of drumming should the system support?

**Answer:**

The system should initially support individual hits, alternating right/left hits, repeated hits, rapid consecutive hits, and simultaneous or near-simultaneous hits when the camera and processing pipeline can reliably support them.

---

### 13. What playing speed should the system support?

**Answer:**

The target speed should be sufficient for realistic beginner/intermediate-level drumming. However, the exact maximum BPM or hit rate should be determined experimentally after testing with real drumsticks.

---

### 14. How should strike intensity be handled?

**Answer:**

Strike intensity should initially be estimated from kinematic motion, such as velocity near the predicted impact point. It should explicitly be treated as an intensity proxy rather than a physical measurement of impact force. In the first version, it can be mapped to volume or MIDI-like velocity.

---

### 15. Should the system distinguish different types of hits?

**Answer:**

Initially, the system should distinguish between drum zones rather than advanced articulation types. More advanced types such as Rim/Center/Edge Hits can be considered future work unless they become important to the research contribution.

---

# C — Virtual Drum Kit

### 16. How many virtual drum zones should the final system contain?

**Answer:**

The MVP should start with approximately 4 zones, while the V1 target is approximately 7 zones. The exact final arrangement should be confirmed before implementation.

---

### 17. What virtual drums should exist?

**Answer:**

An initial drum kit should include:

- Snare
- Hi-Hat
- Tom 1
- Tom 2
- Floor Tom
- Crash/Ride

Kick may require a separate decision because foot tracking is currently outside the V1 scope.

---

### 18. Should the drum zones be fixed or movable?

**Answer:**

The drum zones should initially be fixed.

---

### 19. How should the user's playing position be determined?

**Answer:**

I do not want the user to manually determine the position. The system itself should define the area where the user needs to stand, similar to a designated area shown directly in the webcam view.

---

### 20. Should the virtual drum kit look realistic or geometric?

**Answer:**

The initial version should prioritize clear geometric zones and low-latency interaction. A more realistic drum-kit interface can be added later without changing the core Detection/Prediction architecture.

---

### 21. Is depth estimation required?

**Answer:**

No, not in the initial version. The core interaction should use a 2-D camera coordinate system and virtual drum geometry. Depth Estimation can be considered later if experiments show that it is necessary.

---

# D — Camera & Computer Vision

### 22. What camera will be used?

**Answer:**

Initially, the normal laptop webcam will be used. Later, the project can be upgraded to a stronger external camera, and an iPhone camera may also be considered.

---

### 23. What frame rate is the target?

**Answer:**

The baseline is 30 FPS, with a target of true 60 FPS if the camera and computer can support it reliably. Fake/interpolated FPS must never be presented as native camera FPS.

---

### 24. Should the camera be fixed?

**Answer:**

Yes. The camera should preferably be mounted on a stable tripod or kept in a fixed position to maintain consistent geometry and tracking.

---

### 25. How far should the user be from the camera?

**Answer:**

The distance should be determined through camera and interaction benchmarking. The setup should provide enough field of view for both hands and the drumstick movement paths without excessive loss of tracking resolution.

---

### 26. What part of the user needs to be visible?

**Answer:**

The main requirement is that both hands and enough surrounding space are visible so that the drumsticks can move through the virtual drum zones. Full-body tracking is not required for V1.

Kick/foot interaction can be added later if needed.

---

### 27. What lighting conditions should the system support?

**Answer:**

The system should support normal indoor lighting and should be tested under multiple realistic lighting conditions rather than assuming controlled laboratory lighting.

---

### 28. Does the background need to be controlled?

**Answer:**

No. The goal is for the system to work in a normal environment. However, background clutter and occlusion should be considered during evaluation.

---

### 29. Can other people or objects appear in the background?

**Answer:**

The system should preferably remain stable when people or objects are present in the background. Multi-person interaction is outside the project scope. Testing should include some realistic background variation.

---

### 30. Does the color of the drumsticks matter?

**Answer:**

The target is Markerless Operation, so ordinary drumstick colors should be supported. Colored tape may only be used as a fallback or benchmark condition.

---

# E — Stick Tracking

### 31. How should the drumstick tip be detected?

**Answer:**

Hand Landmarks should be used as a primary reference, combined with visual stick information to estimate the stick axis and tip geometrically. The implementation should remain modular so that Markerless Geometric Tip Estimation, Visual Stick-Axis Refinement, and marker-based fallback methods can be compared.

The intended direction is:

Hand Landmarks
+
Visual Stick Segmentation
+
Stick Axis Estimation
+
Tip Estimation

---

### 32. Does the user need to hold the drumsticks in a specific way?

**Answer:**

The system should assume a natural drumstick grip while allowing a reasonable degree of variation in grip and stick orientation.

---

### 33. Should the system automatically identify the left and right hands?

**Answer:**

Yes. Each hand should have an independent Tracking State, Kinematic State, and Prediction State.

---

### 34. What should happen when the drumstick is temporarily occluded?

**Answer:**

The system should tolerate short tracking interruptions using the available causal state when it is safe to do so, but it must never use future information. If tracking becomes invalid or stale, the Predictor/Feature History should be reset as appropriate.

---

### 35. What should happen if tracking is lost for approximately 100–300 ms?

**Answer:**

The system should enter a safe Invalid Tracking state. Predictor/Kinematic history should be reset when necessary, and the system should re-enable prediction after valid tracking returns. The system must not fabricate a strike during the tracking-loss period.

---

# F — Impact & Strike Definition

### 36. What exactly counts as a drum strike?

**Answer:**

A strike is geometrically defined as the first valid downward/inward entry or crossing of the estimated drumstick-tip trajectory through the boundary/interior of a virtual drum zone according to the project's impact convention.

---

### 37. Must the drumstick approach the drum zone downward?

**Answer:**

Yes. The current definition considers downward/inward entry into the zone a valid strike and does not consider arbitrary upward crossings to be strikes.

---

### 38. Do we need the exact impact position?

**Answer:**

Yes, when available. The system should retain the estimated impact position and the corresponding drum zone because this supports later analysis and more accurate timing and trajectory evaluation.

---

### 39. Do we need sub-frame impact timing?

**Answer:**

Yes. When two observations surround the estimated crossing time, the impact timestamp should be estimated using interpolation instead of simply choosing the nearest camera frame.

---

### 40. How early should the AI predict a strike?

**Answer:**

There is currently no fixed validated value. The goal is to maximize useful Prediction Lead Time while controlling False Positives and Timing Error. Candidate lead times should be determined experimentally rather than assumed.

The important requirement is that the prediction should happen early enough to avoid noticeable delay while still producing reliable and accurate strikes.

---

# G — AI / Machine Learning

### 41. What exactly should the AI predict?

**Answer:**

The target is a multi-task prediction problem involving:

- Whether a strike will occur within a short time horizon
- Time-to-Impact
- Impact/Strike Zone
- Impact Position when useful
- Intensity Proxy

However, the main AI direction is Future Trajectory Prediction.

---

### 42. Should the AI predict the impact directly or predict the trajectory first?

**Answer:**

Trajectory first.

The intended concept is:

Past Motion
→ Future Trajectory Prediction
→ Virtual Drum Geometry
→ Strike

The AI should understand/predict the future motion of the drumstick first. When the predicted trajectory reaches/intersects a virtual drum zone according to the impact geometry, the system should determine the predicted strike.

---

### 43. Should there be one multi-task model?

**Answer:**

The preferred direction is a causal temporal model that understands recent hand/stick motion and predicts future trajectory and strike-related information. Simpler baselines should remain available for comparison.

---

### 44. Which model architectures should be evaluated?

**Answer:**

The planned candidates are:

- Gradient-Boosted Decision Tree baseline
- GRU
- TCN
- Tiny Transformer as an optional model if it is computationally justified

The final model should be selected based on validation performance and real-time CPU inference cost, not accuracy alone.

---

### 45. What are the most important evaluation metrics?

**Answer:**

The main metrics should include:

- Prediction Lead Time
- False-Positive Rate
- False-Negative Rate
- Timing Error
- Zone Accuracy
- Trajectory Error
- Intensity Error / Proxy Agreement
- Inference Latency
- End-to-End / Effective Latency where measurable

The main research visualization should investigate the relationship between Useful Prediction Lead Time and False-Positive behavior.

---

# H — Dataset & Experiments

### 46. Who will provide the recordings?

**Answer:**

The target dataset is approximately 10–12 participants, with one or two sessions per participant depending on participant availability and the time available for the project.

---

### 47. Should participants follow a fixed protocol or freestyle?

**Answer:**

We should start with a fixed/structured protocol first and then decide whether free/natural playing should be added based on the results.

---

### 48. Should the dataset contain negative examples and fake-outs?

**Answer:**

Yes. The dataset should contain:

- Normal movement
- Stick movement without a strike
- Fake swings
- Stopping before impact
- Movement between zones
- Tracking interruptions
- Different speeds
- Different distances
- Realistic lighting variations
- Occlusion cases

This is important for controlling False Positives.

---

### 49. Should the dataset become a reusable research dataset?

**Answer:**

Yes, if practical and permitted. The dataset should contain reproducible metadata, participant-level splits, clear labeling rules, and documentation so it can support the project's experiments and potentially future research.

---

# I — Final Success Criteria

### 50. What are the THREE most important things that must succeed for Space Drums to be considered a successful graduation project?

**Answer:**

1. Real-time webcam-based virtual drumming should work reliably enough to demonstrate actual drum strikes using ordinary drumsticks.

2. The Temporal Prediction system should demonstrate useful and measurable Prediction Lead Time compared with the Reactive Baseline without unacceptable False Positives.

3. The project should provide a scientifically defensible evaluation showing whether prediction actually improves Action-to-Sound timing, while clearly documenting the limitations of the approach.

---

# J — Additional System Requirements

### 51. Should the system support only one drummer at a time?

**Answer:**

Yes. Single-user interaction is the scope for V1.

---

### 52. Should the system work completely offline?

**Answer:**

Yes. The intended system should run locally without requiring Cloud APIs or an internet connection.

---

### 53. Should the system use real recorded drum samples?

**Answer:**

Yes. The Drum Engine should use local drum samples rather than generating synthetic drum sounds during runtime.

---

### 54. Should the system support MIDI?

**Answer:**

MIDI is not required for the Core MVP. It can remain an advanced/future feature if time allows.

---

### 55. Should Kick/Foot Tracking be included?

**Answer:**

Not in V1. Kick/Foot interaction is currently outside the scope unless the project scope is explicitly expanded later.

However, the architecture should not make future Kick/Foot interaction impossible.

---

### 56. Should the user be able to change drum sounds?

**Answer:**

Preferably yes in a later UI/Configuration stage, but this is not a core research requirement.

---

### 57. Should there be a Calibration Wizard?

**Answer:**

Yes. Eventually, the system should have a Calibration Wizard that determines the camera/playing area and the virtual drum-zone positions. However, it does not need to be part of the earliest prototype.

---

### 58. Should the application expose debugging information?

**Answer:**

Yes. A Debug/Developer Overlay should expose:

- Tracking state
- Hand landmarks
- Stick-tip position
- Stick velocity
- Prediction
- Predicted trajectory
- Drum zone
- Time-to-Impact
- Commit decisions
- Timing information

This information is important during development and experiments.

---

### 59. Should the final demo prioritize visual appearance or scientific evidence?

**Answer:**

Both are important, but scientific correctness and measurable behavior have priority over visual polish. The final demo should clearly communicate the research contribution while still looking like a polished application.

---

### 60. What must NEVER happen in the project?

**Answer:**

The project must never fabricate recordings, dataset samples, experimental results, accuracy, latency, FPS, or real-stick validation.

The system must never use future frames in a model that is supposed to be causal.

The project must never claim that prediction guarantees sound playback before physical impact unless this behavior has been experimentally measured and clearly defined.

The project must preserve the distinction between:

- Target
- Measured
- Historical
- Pending

for all experimental claims.

---

# Confirmed Core Architecture

Based on the current project decisions, the intended high-level architecture is:

Webcam
↓
Fixed Playing ROI
↓
Hand Detection / Hand Landmarks
+
Markerless Visual Stick Detection / Segmentation
↓
Stick Axis Estimation
↓
Stick Tip Estimation
↓
Causal Temporal Tracking
↓
Kinematic Features
↓
Future Trajectory Prediction
↓
Virtual Drum Geometry
↓
Predicted Trajectory / Zone Intersection
↓
Strike Prediction
↓
Time-to-Impact
↓
Commit / Refractory / Duplicate Suppression
↓
Drum Engine
↓
Audio Scheduling
↓
Drum Sound

---

# Core Research Direction

The core research direction is:

> Causal temporal prediction of future drumstick trajectory from monocular webcam-based hand and stick motion, followed by geometry-based virtual impact determination and latency-aware audio scheduling.

The project should evaluate whether this prediction-based approach provides useful Prediction Lead Time and reduces effective Action-to-Sound Latency compared with reactive detection, while maintaining acceptable False-Positive and Timing-Error behavior.

---

# Important Scope Rules

The following are currently outside the core V1 scope:

- ESP32
- IMU sensors
- Electronic stick hardware
- Multiple users
- Full-body tracking
- Mandatory depth estimation
- Foot/Kick tracking
- MIDI as a core requirement
- Cloud processing
- Mandatory visual markers

Marker-based tracking may only be used as a fallback or benchmark.

---

# Current Project Philosophy

The project should prioritize:

1. Scientific correctness
2. Causal processing
3. Measurable performance
4. Real-time behavior
5. Robust Computer Vision
6. Meaningful temporal prediction
7. Clear experimental comparison
8. Reproducibility
9. Honest reporting of limitations

Visual polish is important, but it must not replace scientific validation.