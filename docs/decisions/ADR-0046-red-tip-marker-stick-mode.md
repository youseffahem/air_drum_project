# ADR-0046 — Red painted stick tips as the product STICK mode (a MARKER condition)

Date: 2026-10-16, revised 2026-10-17 (last section). Status: implemented candidate; labelled offline
evidence; live acceptance not measured.

The owner painted both stick tips red and asked for STICK mode to match the fingertip mode's
experience. The visible-stick estimator depends on a MediaPipe hand first. In the 2026-10-16 stick
session (`dev-product-20261016-001915`) it found a hand in 87 of 520 hand-frames and measured 26
endpoints. Fingertip sessions show the reference: perception p50 about 27 ms (all of it the hand
model), software capture-to-audio-schedule p50 about 46 ms, 25-29 FPS.

## Decisions

- **New perception, unchanged decisions.** `stick/red_tip.py` segments red in HSV (both sides of
  the hue wrap; a closing plus filled-contour moments make the glossy reflection irrelevant).
  `stick/red_tip_tracker.py` tracks both tips. `stick/red_tip_estimator.py` emits the existing
  `StickObservation` / `EndpointEvidence` contracts. The measured-output tracker, measured stroke
  geometry, commit policy, zones, calibration and audio are unchanged.
- **Labelled MARKER (integrity I-7, REQ-211).** Painted tips are a coloured-marker condition. Every
  record carries `method_id = MARKER`, the estimator logs `MARKER_WARNING`, and the play report has
  `tip_method: MARKER`. The product pipeline accepts `MARKER` besides `AXIS_REFINED`; nothing else in
  that check changed.
- **No hand model by default.** `app/red_tip_perception.py` runs only the colour tracker, about 2-3 ms
  per frame offline at 640 x 480. `--hand-assist` (or `stick_tip.hand_assist`) also runs MediaPipe.
  It then labels new tips by the nearer grip and vetoes births far from both hands.
- **Predictions never strike.** The tracker predicts only to gate association. A coasting tip is
  reported `UNCERTAIN` with no coordinates, so the pipeline bridges it exactly as it bridges a lost
  fingertip. Ambiguous identities (touching or crossing tips) are reported unmeasured. When the
  ambiguity ends, the pipeline restarts both hands' strokes (`DecisionPipeline.reset_hand`).
- **Identities.** Two slots bind to confirmed tracks; the larger camera x becomes LEFT (measured
  convention). Continuity keeps the labels, so they are stable identities, not guaranteed anatomical
  hands. Extra internal tracks absorb red objects in the room. A track that never moved yields its
  slot to a moving one.
- **Delay only at birth.** A new tip needs two consecutive frames. A tracked tip adds no smoothing:
  the observed centre goes straight to the existing measured-output tracker. A blurred streak is
  re-segmented with lower floors inside the track gate, so the track survives the strike.
- **Configuration.** `configs/red-tip.candidate.yaml` is merged only with `--red-tips`, so fingertip and
  visible-stick configurations and hashes are byte-identical. `product.stick_tip` is an optional,
  additive 1.11 schema block, following the `lead_s` / `pads` precedent. `--stick-tip-config FILE`
  accepts only a `product: stick_tip:` fragment.

## Evidence and limits

- **Synthetic tests** cover:
  - brightness and hue wrap;
  - reflections, blur, occlusion and clipping;
  - distractors and crossings;
  - expiry and flicker;
  - identity of the strikes with perfect measurements, rolls and non-strikes;
  - the occluded crossing.
- **Replays of recorded fingertip trajectories** (`scripts/analyze_red_tips.py replay-fingertips`)
  render synthetic red tips on real motion. They measure agreement with the fingertip pipeline, not
  real-world accuracy.
- **Real-camera evidence is PENDING:**
  - tip continuity with painted sticks;
  - false and missed strikes against counted ground truth;
  - software and acoustic latency.

  The protocol and tools are in `docs/perf/red-tip-stick-mode.md`.
- The camera exposure (-5 developer demo, -6 production) is unchanged. Long exposures smear a fast
  tip, so an exposure A/B in stick mode is an owner decision.

## Revision 2026-10-16 (later): track the painted caps themselves

The owner sent a photo of the painted sticks and reported that tracking did not lock onto the tips.
Three live `--red-tips` sessions that day (`dev-product-20261016-134746`, `-152425`, `-175133`) and
the photo show why.

- **The strong floor (S >= 170) rejected most of the real paint under live exposure.**
  - Strong blobs had a median area of 22 px^2, while the full tip was only found by the weak
    re-detection (113-125 px^2).
  - After 4 such frames a slot becomes `WEAK_LIMIT` and is never measured: 549 of 840 LEFT frames in
    `-175133`.
  - The measured share was 24-65 %.
- **Distractors filled the track table** (7450 refused births in `-134746`), and blobs were ranked by
  area alone.
- **The reported point was the centroid of the whole red region.** On the photo, paint has run down one
  shaft, so the region's centroid lies about 13 native px below the cap.

### Decisions

- **Hysteresis on colour, with hue as the separator.**
  - Seed pixels are the core hue band (H <= 4 or >= 170) with S >= 145 and V >= 60, opened 3 x 3 so
    scattered skin and noise seeds vanish.
  - Growth (the band widened by 3, S >= 70, V >= 40) is kept only within 4 px of a seed.
  - Bright, unsaturated reflection pixels near seeds connect fragments. They join a shape only inside
    the paint's convex hull, so a reflection cannot split a cap and a bright wall cannot add a ring.
- **Colour share.** A region needs a 45 % seed share, else it is `OFF_COLOUR`. On the photo the caps
  have 0.74-0.78, while the ear, lips and skin edges fall below.
- **Blur keeps strong evidence without opening the door to skin.** Motion blur dilutes saturation, so
  a blurred tip's region can fail the 45 % share. Its saturated core alone (`RedDetection.cores`) may
  continue a *bound* track: inside the recovery reach, and counted as OBSERVED. It never starts one. On
  the faster replay at 0.9 blur this restored 141 of 178 matched strikes (first version 139). Accepting
  cores as new tips would have brought back 13-23 false-positive frames on two captures.
- **The cap point.** `RedBlob.center` is the centre of the more saturated end window of a long region
  (paint about 8 % more saturated than a paint run); otherwise it is the filled centroid. Blur streaks
  keep the mid-exposure centroid. The whole region's centroid is kept as `region_center` for
  diagnostics only.
- **Floor selection rule, declared before measuring:**
  - (a) on the photo at tracking scale, both caps are accepted and nothing else;
  - (b) on `data/dev-captures` (sticks not painted), no more frames with an accepted blob than before;
  - (c) no regression of the synthetic and replay suites.

  The result was S >= 145: the lowest floor with 0 accepted blobs on all five captures.
- **Tracker changes.**
  - A higher-scoring new blob may evict an unbound, idle or tentative track at the limit (default
    `max_tracks` 6).
  - While more unbound tracks than free slots exist, only a *moving* track may bind. A stick held still
    and a red object look alike, so the tracker waits for motion instead of guessing.
  - The cost is a startup delay of about 4-5 frames when red clutter is in view.
- **Tools.**
  - `scripts/tune_red_tips.py`: trackbars, cap-point crosshairs and HSV readout. It writes
    `configs/red-tip.tuned.yaml`.
  - A label mode for the true cap centres.
  - `scripts/analyze_red_tips.py frames --labels` measures detection rate, pixel error and identity
    swaps on real footage.

HAND mode (`--fingers`) and the default visible-stick mode are untouched. A test asserts that they never
construct the colour perception and carry no `stick_tip` block. Real-footage accuracy remains
**PENDING** the owner's labelled recording (`docs/perf/red-tip-stick-mode.md` section 8).

## Revision 2026-10-16 (evening): playing distance

The owner reported that tracking works only close to the camera. The recording
`dev-product-20261016-225435` (622 frames at playing distance, exposure -5, `--record-frames`) shows why.

- **The caps are about 11 px across, and dark.** V is 27-58 and the hue is shifted toward magenta
  (signed -61…-9, S 52-144) under the room's dim teal light. Only 0.3 % of cap pixels pass the red seed
  floors, so the default detector measured **0 of 28** held-out labelled caps.
- **This is light, not geometry.** At close range the paint is lit and reads red. At playing distance the
  red signal is about 10 levels of R−G. Gain doubles brightness and noise alike (camera-quality study);
  exposure -4 halves the FPS.
- **A second cause showed in the live session `-225536`.** Both slots sat on blobs clipped by the bottom
  edge (hands, sofa) for most of the session.

### Decisions

- **Border-clipped tracks never take a free slot or adopt a coasting one** (default path). A clipped blob
  is never measured, so binding it only blocked the slot.
- **Opt-in dark-paint pass** (`stick_tip.dark_paint`, default **off**). Default behaviour and the
  false-positive evidence of the red path are unchanged.
  - **Colour:** a wide pixel band (signed hue -60…+5, S ≥ 60, V 20-110, R−G ≥ 6), then per-blob averages
    (hue ≤ -20, R−B ≤ 4, S ≥ 85, V ≥ 32) measured on the recording.
  - **Shape:** a cap merged with the dark upper shaft is cut free at the region's wider end.
  - **Starting a track:** a dark blob starts a track only with a bright surround (≥ 65 % of 16
    directions: the stick held up) and after 4 consecutive frames. Afterwards the bound track follows it
    anywhere.
  - **Evidence:** measurements are reported as state `DARK`, reason `RED_TIP_DARK`, confidence 0.8
    (VALID).
  - **Never:** a prediction is still never a measurement.
- **Tools.** `scripts/tune_red_tips.py --calibrate-dark LABELS` derives a profile from labelled caps,
  choosing the blob limits by recall minus non-cap blobs. On this recording it was worse than the
  measured defaults, so it is documented as a starting point for other rooms, to be verified with
  `analyze_red_tips.py frames --labels`.
- **Recommendation to the owner:** more light on the sticks. The offline numbers are in
  `docs/perf/red-tip-stick-mode.md` section 10. Live validation at distance is **PENDING**.

## Revision 2026-10-17: caps by local redness, a fitted verifier and evidence tracking

The owner asked for reliable, continuous tracking of both caps at playing distance. Four recordings
(`dev-product-20261016-225435`, `-20261017-005436`, `-005615`, `-005812`; exposure -5, teal room light) were
labelled by the assistant (239 visible caps; files flagged as assistant-made, correctable with
`tune_red_tips.py --label`).

- **The colour detector loses the caps before tracking starts.** There was no candidate at the cap for 224
  of 232 labelled caps. The caps are dark (V 37-52) and magenta-shifted, and in this light pixel colour
  overlaps skin, wood and cloth. Dark-paint mode reached caps but measured mostly hands and cloth (52 of
  55 points false on 005615).
- **Stick geometry was tried first and failed its declared gate:** shaft ends reached 49-66 % of caps.
- **Local redness contrast works.** A difference of Gaussians of `min(R-G, R-B+12)` puts 94 % of labelled
  caps among the 12 strongest candidates.

### Decisions

- **New default detector, `stick_tip.detector: redness`** (`stick/red_tip_caps.py`). The HSV detector and
  its tracker stay available as `detector: colour` (bright light, close range, `tune_red_tips.py`).
  - **Candidates:** DoG peaks at half resolution, each grown into a closed region. The point is the centre
    of the region's largest inscribed circle: the ball, with highlights filled; the painted neck and a
    paint run are narrower. Candidates joined by a red path are one stick end (`SAME_CAP`). A ball cut by
    the border is `clipped`.
  - **Verifier:** a logistic score over eight region features: response, relative response, redness
    contrast, brightness, saturation, highlight, *orange* = max(0, hue) and *blueness* = max(0, -hue).
    Features are standardised, L2 = 1, and there is no new dependency.
  - **Why hue is split:** a single hue term was fitted with the wrong sign, because the labelled junk was
    mostly bluish, and it then rated skin as cap-like on the unpainted captures. The split terms
    penalise orange (skin, wood) explicitly.
  - **Coefficients:** the built-ins come from all labelled frames. `analyze_red_tips.py fit-verifier`
    refits them from the owner's labels into a `--stick-tip-config` fragment.
  - **Limits:** this is a learned component fitted on assistant labels from one room. Its limits are in
    `docs/perf/red-tip-stick-mode.md` section 11.
- **New tracker for it** (`stick/red_tip_evidence.py`), sharing `SlotState` / `TrackerFrame`:
  - **Evidence:** a running average of the verifier quality. A slot is measured only with enough evidence
    and enough quality this frame; otherwise it is `LOW_EVIDENCE` (seen, never used for a stroke).
  - **Stillness** lowers a track's *rank* (slot competition), never its measurement, so a stick held still
    strikes at once. A track that never moved yields to a moving tip, and the new pair is ordered like a
    joint binding.
  - **Slot changes:**
    - **adoption:** a coasting slot takes a tip reborn within reach. Its stroke continues unless the other
      stick is unseen too.
    - **challenges and takeover:** a clearly better tip takes a weaker slot, and a live tip takes a slot
      coasting for `takeover_s`.
    - **identity memory:** a returning tip goes back to its own slot.
    - **instant binding** is allowed only for a stick reacquired where a slot last measured, so a
      single-frame red flash is never measured.
  - **Blur:** the verifier learned still caps and scores a strike-speed streak near 0. A bound tip
    measured `OBSERVED` within 0.2 s continues on a moving low-quality candidate as `WEAK` (confidence
    0.75) for at most `max_weak_frames` frames. `WEAK` never starts a measurement. A tip leaving rest may
    take a candidate within twice its gate, never beyond `gate_max_px`.
  - **After an ambiguous merge,** the two tracks take the slots whose last measurements they are nearer
    to, and both strokes restart.
- **Unchanged:**
  - predictions never carry coordinates;
  - contracts and MARKER labelling;
  - the decision pipeline, calibration and audio;
  - HAND mode and its configuration (`--fingers`);
  - the native and standard camera paths.
- **Evidence:** offline, labelled before/after results on identical frames are in
  `docs/perf/red-tip-stick-mode.md` section 11. Live validation, unique FPS and strike counts are
  **PENDING** the owner's run.
