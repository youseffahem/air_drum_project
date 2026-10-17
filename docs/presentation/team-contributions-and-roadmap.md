# Six-role responsibility map and roadmap

17 October 2026. These are project responsibilities, **not evidence of individual authorship**. Member names, institution and supervisor were not verified. Assign names during rehearsal. The team leader is one of the six members, not a seventh speaker.

## 1. AI and Computer Vision

- **Responsibility:** deliver trustworthy current-frame hand/fingertip or stick-tip measurements, with honest absence/confidence states.
- **Existing evidence:** `app/main.py:Perception`, `hands/landmarker.py:HandLandmarker`, `hands/identity.py`, `stick/visible.py:FingertipEndpointEstimator` and `VisibleEndpointEstimator`; `app/red_tip_perception.py:RedTipPerception`, `stick/red_tip.py:RedTipDetector`, `red_tip_tracker.py:RedTipTracker`, `red_tip_estimator.py:RedTipEndpointEstimator`.
- **Status:** HAND and visible endpoint paths implemented. Painted-tip detection/tracking is an uncommitted developer candidate. Optional dark mode is experimental. Research GRU/TCN/LightGBM code exists, but is not evidence of a validated live anticipation model.
- **Problems:** dim paint shifts hue/saturation; blurred caps and red clutter cause loss or wrong association; held-stick hands are difficult; overlapping tips become ambiguous. Confidence classes are not accuracy estimates.
- **Remaining work:** independent tip labels, playing-distance lighting trials, crossings/occlusions, detector precision and identity evaluation.
- **Dependencies:** core supplies stable frame timestamps/geometry; strike role identifies which losses cause missed events; UI exposes reasons.
- **Next step and acceptance:** agree a held-out recording set; label both tips and absences; publish error, recall, distractor matches and identity swaps separately. The team must set acceptance thresholds before scoring. No claim of success until that evaluation exists.

## 2. Strike Detection and Motion Analysis

- **Responsibility:** turn valid motion into one intended drum event with controlled repeats and explicit rejection reasons.
- **Evidence:** `geometry/strokes.py:MeasuredStrokeGeometry.observe`, `geometry/impact.py:segment_surface`, `geometry/zones.py:ZoneRegistry`, `commit/policy.py:PerHandCommitPolicy`, `commit/state_machine.py`, `tests/product/test_four_pad_product.py`, `tests/product/test_red_tip_play.py` and gap/causality tests.
- **Status:** measured-stroke geometry and commit gates implemented. Product Arm A only; demo adds 33 ms edge look-ahead. The fresh synthetic full-kit ordering test fails reproducibly (tom2 where snare is expected); diagnosis and a regression fix remain work for this role with core processing.
- **Problems:** a full downward sweep can consume an upper zone before the intended lower one; stop-short movements can trigger with look-ahead; missing endpoints prevent decisions. No independent live wrong-zone or recall result.
- **Remaining work:** time-aligned intended-hit truth, non-strike sequences, roll/rebound tests, look-ahead comparison and confusion matrix.
- **Dependencies:** CV measurement quality, core frame/drop contracts, calibrated zone registry and audio event logging.
- **Next step and acceptance:** annotate counted singles, alternating strokes and intentional non-strikes in all modes. Report correct/missed/duplicate/wrong-zone events using a predeclared matching rule. Test every approved behavioral change with a focused regression.

## 3. Frontend and User Interface

- **Responsibility:** show zones, input state, calibration guidance and diagnostic information clearly.
- **Evidence:** `ui/stage.py:StageRenderer`, `ui/developer_demo.py:DemoOverlay`, `ui/kit.py:render_kit`, `ui/layout_preview.py:LayoutPreview`, `ui/preview_tone.py:PreviewTone`, `ui/dashboard.py`, `ui/wizard_views.py` and `tests/ui/`.
- **Status:** OpenCV desktop UI implemented, including seven-piece full kit, four-pad view, diagnostics and layout preview. There is no browser or mobile frontend.
- **Problems:** some instructions describe old defaults; full-kit view alone does not prominently establish calibration acceptance; a counter/stream state may be mistaken for a correct audible hit. Small diagnostics need enlarged presentation screenshots.
- **Remaining work:** consistent mode/calibration wording, clearer tracking loss guidance and usability review after geometry stabilizes.
- **Dependencies:** CV reasons, core health/status records, calibration states, audio health and strike events.
- **Next step and acceptance:** draft a small set of status messages using existing contracts and test them in a rehearsal. Users should correctly distinguish fixed-guide demo, fitted verification, ready state, missing tracking and audio loss. Any UI changes are future work; none were made in this audit.

## 4. Backend and Core Processing

- **Responsibility:** connect capture, perception, per-hand decisions and sound with reproducible configuration and logs.
- **Evidence:** `app/play.py:run`, `app/pipeline.py:DecisionPipeline`, `capture/source.py:LiveFrameSource`, `capture/replay.py:ReplayFrameSource`, `contracts/records.py`, `contracts/perception.py`, `config/loader.py`, `app/arms.py` and architecture/system tests.
- **Status:** local Python orchestration implemented, with replay, strict frame identity, queue/drop accounting, model fallback and structured evidence. No HTTP backend or mobile transport exists.
- **Problems:** old docs and current defaults disagree; package metadata alone omits a hand-model dependency; product calibration and research per-arm routes have different contracts. Final release acceptance remains pending.
- **Remaining work:** reconcile docs after decisions, verify clean installation, preserve source/config hashes for each session, complete representative integration runs.
- **Dependencies:** every component's stable interfaces, CV resets, strike gate semantics, audio device behavior and external validation inputs.
- **Next step and acceptance:** replay a fixed evidence set from a pinned environment and verify current-frame causality, replay provenance, known error handling and no unintended shadow audio. Produce a repeatable setup checklist before packaging.

## 5. Mobile Application Development

- **Responsibility:** clarify whether a mobile deliverable belongs to this project, then define a feasible approved role.
- **Evidence:** no mobile source/build project, platform manifest or approved mobile requirement found. `project-discovery.md` and `docs/requirements/out-of-scope.md` mention a possible later external/iPhone camera, which is **not a mobile app implementation or approval**. Runtime processing is intended to remain local.
- **Status:** **not implemented; scope unresolved**. The intended six-person role in the presentation request does not prove an approved repository feature.
- **Problems:** no product requirements, platform choice, protocol or integration contract; adding streaming may change latency, privacy and local-only assumptions.
- **Remaining work:** team/supervisor decision on whether mobile is included, user need, platform and ownership. No technology choice is implied by this roadmap.
- **Dependencies:** core must expose an approved interface if one is needed; UI and audio define useful controls/status; the team reviews scope against local-only requirements.
- **Proposed next step:** write a one-page scope decision comparing a local session-summary viewer with a companion controller and deferral. A summary viewer can initially use manually exported nonsensitive JSON and need no live network dependency. This is a proposal subject to approval.
- **Acceptance if approved:** document a versioned minimal schema, create an actual platform build, load one exported session summary, label stale/unavailable values and test offline/error behavior. Do not demonstrate remote hit triggering or streaming until separately specified and measured.

## 6. Audio and Music Engine

- **Responsibility:** map committed strikes to appropriate sample playback and measure what the user hears.
- **Evidence:** `app/audio_out.py:AudioOutput`, `audio/bank.py:SampleBank`, `audio/gain.py:GainCurve`, `audio/variants.py:VariantSelector`, `audio/scheduler.py:AudioScheduler`, `audio/mixer.py:CallbackMixer`, `audio/device.py:SoundDeviceOutput`, sample manifests and `tests/audio/`.
- **Status:** local sample playback, velocity-style gain, soft/hard layers, round-robin takes, polyphony, scheduling and recovery implemented. Audio preflight passed. No fresh acoustic test was conducted for this package.
- **Problems:** intensity is a kinematic proxy rather than force; scheduling/device latency differs from physical action-to-sound delay; shadow events must stay silent; old voice backlog must clear on recovery.
- **Remaining work:** audible zone/sample verification, overlap/underrun checks under representative play and an accepted external latency measurement.
- **Dependencies:** correct zones and timestamps from strike/core, stable camera timing, sample assets/licenses and an external timing reference.
- **Next step and acceptance:** verify each zone's sound at a safe level with a human listener, then use the approved physical timing method. Publish uncertainty and conditions. A 128-frame buffer at 48 kHz does not establish end-to-end latency.

## Shared sequence

1. Investigate the reproducible synthetic full-kit sequence failure (tom2 where snare is expected); freeze an evidence set and agree independent labels before tuning.
2. Resolve tracking and intended-zone failures together.
3. Validate calibration and measure audio response externally.
4. Run integration/regression checks and update the launch documentation.
5. Decide mobile scope and participant/release prerequisites explicitly.

All dates, thresholds and member names beyond the audit date require team agreement. This is a dependency-ordered proposal, not a promised delivery schedule.
