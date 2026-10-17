# Red painted stick tips: STICK mode by colour (`app.play --red-tips`)

Date: 2026-10-16, revised the same day after the owner's photo of the painted sticks. Decision record:
[ADR-0046](../decisions/ADR-0046-red-tip-marker-stick-mode.md), including its revision section.

**Follow-up (2026-10-17, section 12):** the five open failures were investigated event by event:
- extra strikes on the replays fell from 36 to 12, after point jitter was found and fixed;
- the painted neck no longer replaces a dim ball;
- close-range centres improved on the development caps;
- by a precise definition there are no silent identity swaps;
- the long gaps are mostly sticks out of view;
- cut caps stay unmeasured.

Live validation is still **PENDING** (section 12.7).

**Status (2026-10-17, section 11):** the default detector is now `redness` (local redness contrast, a
fitted cap verifier, evidence tracking). On labelled held-out frames of four owner recordings at playing
distance it finds **90 of 115 caps (78 %)**, against 7 (6 %) for the colour detector below and 31 (27 %)
for dark-paint mode, with 0 measured frames on the unpainted captures. Live use is **PENDING** the owner's
run; nothing here is a live claim. Sections 2-10 describe the colour detector (`detector: colour`) and its
history.

**Earlier status (2026-10-16):** implemented, with offline evidence only.
- The detector now tracks the **painted caps themselves** (section 2).
- On the owner's photo both cap points land on the caps (section 5).
- Real-camera accuracy, continuity and latency are **PENDING** the owner's labelled recording (section 8).
- **At playing distance (section 10)** the default detector finds **0 of 28** labelled caps in the owner's
  recording: the caps are dark and magenta-shifted in this light. The opt-in dark-paint mode
  (`dark_paint: true`) measures 23 of 28 offline. **More light on the sticks is the recommended fix.**

Painted tips are a coloured-marker condition: every record says `MARKER` (integrity I-7). Nothing here is
participant evidence.

## 1. Why

| Mode | Source | Tip continuity (after first tip) | Perception p50 | Capture -> audio schedule p50 | FPS |
|---|---|---|---|---|---|
| Fingertip (`--fingers`) | `dev-product-20261016-003327`, `dev-product-20261010-015648` | 90 % / 89 % (L / R) | 27.5 ms | 46 ms | 25.3 |
| Visible stick (default) | `dev-product-20261016-001915` | L never, R 16 % | 29.4 ms | (no hit) | 24.0 |

The visible-stick estimator needs a MediaPipe hand first. In that stick session a hand was found in
87 of 520 hand-frames. The hand model is also the whole perception cost of both modes. The numbers above
come from `scripts/compare_play_sessions.py` on the logged sessions (developer evidence).

## 2. Why the first version missed or misplaced the tips (revision 2026-10-16)

Evidence comes from three live `--red-tips` sessions that day (`dev-product-20261016-134746`, `-152425`,
`-175133`, no frames recorded) and the owner's photo.

| Cause | Evidence |
|---|---|
| **The strong floor S >= 170 rejected most of the real paint.** | Strong (OBSERVED) blobs had a median area of **22 px²**; weak re-detections found 113-125 px² (the real tip). After 4 weak frames a slot is `WEAK_LIMIT`, never measured: LEFT 549/840 frames in `-175133`, 412/816 in `-152425`. Those WEAK_LIMIT tips sat at y ≈ 0.58, where the photo holds the caps. Measured share 24-65 %. |
| **Distractors won slots and filled the track table.** | Blobs were ranked by area alone. `TRACK_LIMIT` refused 7450 births in `-134746` (4 junk tracks). Slots bound to blobs at the bottom border (`CLIPPED` 514 frames, OBSERVED y ≈ 0.88). |
| **The tip point was the centroid of the whole red region.** | On the photo, paint has run down the left shaft. The first version's mask merged it with the cap: an 80 px tall box, and a centre about 13 native px (9 tracking px) below the cap. |
| **Tests never used realistic caps.** | Synthetic tips were 16 × 12 px (151 px²). The photo's caps are about 28 × 37 tracking px (about 1000 px²). There was no paint-run, ear or lip case. |

**Paint colour measured on the photo** (OpenCV HSV; the photo is probably tone-mapped, mean luma 107, so
it guides the design but is not a tracking frame):

| Region | Hue (signed, around 0) | Saturation | Value |
|---|---|---|---|
| Paint | median −1 (IQR −3…+1) | median 190-194 | 117-246 |
| Paint run on the shaft | +5 | 144 | – |
| Lips | +6 | 130 | ~56 |
| Ear | +4 | 134 | – |
| Face | 10-13 | – | – |
| Wood | 12-17 | – | – |

## 3. How it works now

1. **Seeds (the paint core)** (`stick/red_tip.py`):
   - Core hue band H ≤ 4 or ≥ 170 (both sides of the red wrap), with S ≥ 145 and V ≥ 60.
   - Seeds are opened with a 3 × 3 square, so scattered skin and sensor-noise seeds vanish.
   - **Hue is the separator**, not saturation alone.
2. **Growth:**
   - The band widened by 3 hue units, with S ≥ 70 and V ≥ 40, kept only within 4 px of a seed.
   - Edges and mild blur join a cap; a face or hand behind it never does.
3. **Glossy reflections:**
   - Bright, unsaturated pixels (V ≥ 190, S ≤ 80) near seeds connect the fragments a reflection cuts
     apart.
   - They join the shape only inside the convex hull of the paint: a highlight cannot split a cap, and a
     bright wall cannot add a ring around it.
   - Interior reflections are filled.
4. **Colour share:**
   - A region needs at least 6 seeds and a seed share of 45 % or more, else it is `OFF_COLOUR`.
   - On the photo: caps 0.74-0.78. The ear and lips fall below.
5. **The cap point (`RedBlob.center`, what is tracked):**
   - When a region is longer than 1.2 × its width and one end window is clearly more saturated (≥ 8 %;
     photo cap vs paint run: 12.5 %; the two ends of a clean cap: < 5 %), the point is the filled
     centroid of that end.
   - Otherwise it is the filled centroid of the region.
   - The whole region's centroid is kept as `region_center` (diagnostics only).
6. **Blur:**
   - A blurred tip's region can fail the share test (saturation is diluted). Its **saturated core** may
     continue a *bound* track as an OBSERVED measurement, within the recovery reach. It never starts one.
   - Fainter streaks are re-segmented with the weak floors inside the track gate: `WEAK`, at most 4
     frames in a row.
   - Blur positions are the streak centroid (mid-exposure).
7. **Tracking** (`stick/red_tip_tracker.py`):
   - Joint Hungarian association with bounded prediction (gating only), a two-frame birth, coasting for
     0.25 s and LEFT/RIGHT slots, as before.
   - New: a higher-scoring blob (size × seed share) **evicts** an idle or tentative unbound track at the
     limit (6 tracks).
   - New: while more unbound tracks than free slots exist (red clutter), **only a moving track may
     bind**. A stick held still and a red object look alike, so the tracker waits for motion instead of
     guessing.
8. **Unchanged:**
   - **A predicted position is never an observation:** coasting is `UNCERTAIN` with no coordinates.
   - Ambiguous crossings are unmeasured, and both strokes restart afterwards.
   - The contracts (`StickObservation` / `EndpointEvidence`, `MARKER`), the measured-output tracker,
     stroke geometry, commit policy, zones, calibration and audio.
   - No hand model unless `--hand-assist`.
   - HAND mode (`--fingers`) and the default visible-stick mode are untouched, and a test asserts they
     never build the colour perception.

## 4. Launch and live check

```
.\demo-sticks-spacedrums.ps1                       # full kit, red tips (= play --demo --red-tips)
.\demo-sticks-spacedrums.ps1 --kit four            # 2x2 kit
.\demo-sticks-spacedrums.ps1 --stick-tip-config configs/red-tip.tuned.yaml   # after tuning (section 6)
.\play-spacedrums.ps1 --red-tips                   # standing product flow with automatic calibration
.\play-spacedrums.ps1 --fingers                    # HAND mode, unchanged
python -m spacedrums.app.play --demo --red-tips --check        # assets only, no camera/audio
```

In the full-kit view, `D` toggles the diagnostics. The display is mirrored.
- **A filled dot with `L#id OBS` / `R#id OBS`** is the measured cap point. It must sit on the painted
  cap, not on the stick, the hand or the bottom of the red paint. `L` / `R` are the stable stick
  identities (slots); `#id` is the track behind them.
- **An orange ring** is a tip that is seen but not trusted, never used for a strike: `AMBIG` (the two tips
  touch), `EDGE` (cut by the border), `LOW` (redness detector: not enough evidence yet). **A thin ring with
  `PRED`** is a coasting prediction, never measured.
- **Redness detector (default, section 11):** a yellow **outline** is each candidate's cap region, the
  small dot its cap point, `q 0.93` its verifier quality; grey `SAME` marks a second candidate on the same
  stick end (a painted neck, a ball split by its highlight). The inset (`REDNESS`) shows the candidate
  regions.
- **Colour detector (`detector: colour`):** a yellow ring is an accepted blob's cap point, a small grey dot
  the whole red region's centroid when the two differ; the inset shows seeds (red) and growth (dark red).
- **The HUD:** red-tip ms and per-hand state and measured share.

## 5. Offline evidence (2026-10-16 revision), not real-world accuracy

Outputs: `experiments/pre-participant/20261016-red-tip/v2/` (git-ignored). All runs used the final code;
`tree-status.txt` records the working tree. The compute times were measured while other processes ran.

**A. The owner's photo, the one real image of the painted sticks.** It was scaled by 2/3 to the tracking
scale; the photo is probably tone-mapped, so this is not a tracking frame.
- Both caps are tracked (`OBSERVED`).
- Cap points, in tracking px: (191.4, 238.5) for the stick with the paint run, and (448.4, 272.3).
- The stick with the run has its whole-region centroid at (193.6, 254.7): **16 px lower**, on the run.
  The cap point sits on the cap in `v2/photo/contact-sheet.jpg`.
- Ear and lips are rejected (`OFF_COLOUR`). The first version's mask (S ≥ 170, no colour test) also
  accepted a 48 px² blob beside the ear, and merged the paint run into the left cap.

**B. Real frames from the developer room, sticks not painted** (`data/dev-captures`). Any accepted blob
is a false positive.

| Capture | Frames | Frames with an accepted blob, first version | Revision | Red-tip ms p50 / p95, first version | Revision |
|---|---|---|---|---|---|
| dist-d080-L2-exp-5 | 444 | 0 | **0** | 1.58 / 2.14 | 2.32 / 3.81 |
| dist-d080-L2-exp-6 | 443 | 285 | **0** | 2.27 / 3.11 | 2.48 / 3.75 |
| swing-L2-exp-5 | 171 | 16 | **0** | 1.73 / 2.37 | 2.57 / 4.11 |
| swing-L2-exp-6 | 171 | 42 | **0** | 2.07 / 2.95 | 2.69 / 4.01 |
| swing-L2-exp-7 | 172 | 0 | **0** | 1.82 / 2.73 | 2.12 / 3.15 |

The floors follow a rule declared before measuring:
- (a) on the photo, both caps are accepted and nothing else;
- (b) here, no more false frames than the first version;
- (c) no regression in C and D.

S ≥ 145 is the lowest seed floor that met (b). S 140 gave 1/1/1/1/0 false frames; S 120 without the
opening gave 2/3/6/11/2.

**C. SYNTHETIC swings with distractors** (a static red object, a skin-tone blob and speckles in every
frame).

| Case | Tips | Truth | Detected | Missed | False | Same as perfect tips | ms p50 / p95 |
|---|---|---|---|---|---|---|---|
| four-pad strikes | photo-sized | 6 | 6 | 0 | 0 | 6 / 6 | 4.8 / 7.7 |
| alternating roll | photo-sized | 10 | 10 | 0 | 0 | 10 / 10 | 4.3 / 5.1 |
| simultaneous | photo-sized | 2 | 2 | 0 | 0 | 2 / 2 | 4.8 / 6.2 |
| non-strikes | photo-sized | 0 | 0 | 0 | 1* | 1 / 1 | 4.7 / 6.1 |
| full kit | photo-sized | 3 | 3 | 0 | 0 | 3 / 3 | 5.5 / 9.0 |
| alternating roll | first-version 16 × 12 | 10 | 8 | 2 | 0 | 8 / 10 | 4.5 / 6.5 |

\* The perfect-tip pipeline makes the same commit: the synthetic path between swings crosses a pad edge.

With the small tips, the other four cases match the perfect-tip pipeline exactly. The roll loses 2
because a static red object of the same paint is in view: binding waits until the small tips move.
The first version bound them by x order and got 10. Synthetic frames cost more than real ones because
their speckles spread seeds over the whole frame.

**D. SYNTHETIC red tips (first-version size) rendered on recorded fingertip trajectories.** This is
agreement with the fingertip pipeline on the same real motion, not accuracy.

| Session | Blur | Fingertip hits | First version: matched / missed / extra | Revision: matched / missed / extra | ms p50 |
|---|---|---|---|---|---|
| 20261010-015648 | none | 246 | 245 / 1 / 5 | 244 / 2 / 4 | 3.1 |
| 20261010-015648 | 0.5 centred | 246 | 245 / 1 / 1 | 243 / 3 / 5 | 3.1 |
| 20261010-015648 | 0.9 centred | 246 | 239 / 7 / 7 | **243 / 3 / 6** | 2.8 |
| 20261010-015648 | 0.9 trailing | 246 | 175 / 71 / 42 | 172 / 74 / 38 | 2.9 |
| 20261016-003327 | none | 178 | 174 / 4 / 0 | 174 / 4 / 0 | 3.2 |
| 20261016-003327 | 0.5 centred | 178 | 150 / 28 / 6 | 150 / 28 / **1** | 3.6 |
| 20261016-003327 | 0.9 centred | 178 | 139 / 39 / 10 | **141 / 37 / 10** | 3.7 |
| 20261016-003327 | 0.9 trailing | 178 | 145 / 33 / 21 | 142 / 36 / 22 | 3.6 |

Every condition is within ±4 matched strikes of the first version. An intermediate revision without the
blur-core path dropped to 118 at 0.9 centred: blur dilutes the seed share. The core path in section 3.6
restored it.

**Unit tests** (SYNTHETIC) cover:
- two caps; reflections at the centre, rim and outline;
- the paint run at 4 angles × 3 lengths;
- sizes 4-18 px × 5 orientations;
- hue −6…+4 × brightness 0.5-1.25 × S 160-215;
- orange and magenta rejected; skin, ear and lips rejected next to a kept cap; a face touching a cap;
- no tip;
- blur cores; crossings and identity at photo size;
- clutter eviction and deferred binding;
- occlusion and coasting, and prediction never measured;
- the tuner round-trip, label scoring, and the HAND-mode guard.

## 6. Configuration and tuning

`configs/red-tip.candidate.yaml` (block `product.stick_tip`) is merged **only** with `--red-tips`. Every
value is a developer candidate. Tuned values belong in **`configs/red-tip.tuned.yaml`**, written by the
tuner and passed with `--stick-tip-config`.

| Setting | Default | Change it when |
|---|---|---|
| `s_min` / `v_min` | 145 / 60 | The caps are found only in the dark-red inset, not as yellow rings, while still or slow: lower `s_min`. Skin, lips or clothes appear: raise it. |
| `hue_low_max` / `hue_high_min` | 4 / 170 | The paint reads orange under your light (raise `hue_low_max`) or magenta (lower `hue_high_min`). Click a cap in the tuner to read its hue. |
| `s_min_weak` / `v_min_weak` | 70 / 40 | Fast strokes lose the tip (lower them) or a track slides onto skin (raise them). |
| `min_seed_fraction` | 0.45 | A cap with a long paint run is rejected as `OFF_COLOUR` (lower it slightly) or skin passes (raise it). |
| `grow_px` / `open_px` | 4 / 3 | Very small, distant caps vanish (lower `open_px` to 0). |
| `min_area_px` / `max_area_px` | 30 / 4000 | You stand much farther away or much closer. |
| `head_length_factor` / `head_contrast` | 1.2 / 0.08 | The cap point jumps between ends of a long red region: raise `head_contrast`. |
| `ignore_regions` | `[]` | A red object keeps being detected. Boxes are `[x0, y0, x1, y1]` in ROI-normalised **camera** coordinates. |
| `birth_frames`, `max_coast_s`, `gate_*`, `max_weak_frames`, `max_tracks` | 2, 0.25, 28-140, 4, 6 | As in ADR-0046. |

### Tuning on your own recorded frames

1. **Record** 20-30 s of both sticks moving through the kit, and also held still. Recording halves the
   FPS, which is fine for tuning.
   ```
   .\play-spacedrums.ps1 --demo --red-tips --record-frames --max-seconds 30
   ```
   The session folder is printed and appears under `data/dev-product/`. It holds the 640 × 480 tracking
   frames as lossless PNG.
2. **Tune:** `python scripts/tune_red_tips.py data/dev-product/<session>`
   - Trackbars change the floors live.
   - Yellow crosshair = the cap point, grey dot = the region centroid, grey ring + reason = rejected.
   - The inset shows seeds and growth.
   - Click a cap to print its HSV percentiles.
   - `n` / `p` step frames, `m` toggles the full mask, `s` saves `configs/red-tip.tuned.yaml` (validated
     exactly as `app.play` loads it), `q` quits.
3. **Check tracking** over the whole recording, with the tuned file:
   ```
   python scripts/analyze_red_tips.py frames data/dev-product/<session> --stick-tip-config configs/red-tip.tuned.yaml --output experiments/red-tip-check
   ```
   It reports continuity, loss gaps, rejects and red objects that never move, and writes
   `contact-sheet.jpg` with the crosshairs.

## 7. Verify that the coordinates land on the caps (real footage)

1. **Label:**
   ```
   python scripts/tune_red_tips.py data/dev-product/<session> --label --label-every 10
   ```
   - On every 10th frame, click the true centre of the painted cap of **stick A**, then of **stick B**.
     Keep A the same physical stick throughout.
   - `x` = this stick is not visible, `c` = clear the frame, `n` / `p` = move.
   - Labels are saved continuously to `data/dev-product/<session>/red-tip-labels.json`, beside the
     recording (git-ignored). Use `--labels FILE` for another path.
2. **Score:**
   ```
   python scripts/analyze_red_tips.py frames data/dev-product/<session> --labels data/dev-product/<session>/red-tip-labels.json --stick-tip-config configs/red-tip.tuned.yaml --output experiments/red-tip-accuracy
   ```
   `summary.json -> accuracy_vs_labels` gives:
   - `detection_rate` (a measured tip within `--match-px` 12 of the label);
   - `error_px` p50 / p95 / max (the cap point against your click);
   - `measured_tips_near_no_label` (a measured point that is not on a cap);
   - `identity` and `identity_disagreements` (swaps).
3. **A photo works too:** `python scripts/analyze_red_tips.py frames photo.png --scale 0.6667 --output <dir>`.
   Use `--scale` for a 960 × 720 native-window image; label it with the same `--scale`.

## 8. What still needs the real camera (owner, PENDING)

Run these only when you choose; nothing here starts automatically.

1. Record, tune and label as in sections 6 and 7. **Real-footage cap-point error, detection rate and
   identity swaps are not measured yet.** Nothing in section 5 is real-world accuracy.
2. **Count-based comparison.** Use the same position, light and kit, and record each block twice: once
   with `--fingers`, once with `--red-tips`. Use `--max-seconds 25`, one block per run, and count aloud.
   1. 16 strikes on the snare.
   2. 16 strikes on the hi-hat.
   3. 16 strikes on tom 1.
   4. 16 strikes on the crash.
   5. A 16-stroke alternating snare roll.
   6. Cross-stick: 8 hi-hat (right stick crossing over) + 8 snare.
   7. 30 s of moving between drums **without** striking (expect none).
3. **Compare** with one `--run` per block (`MODE DIR EXPECT`):
   ```
   python scripts/compare_play_sessions.py ^
     --run fingers data/dev-product/<f1> snare=16   --run sticks data/dev-product/<s1> snare=16 ^
     --run fingers data/dev-product/<f5> snare=16   --run sticks data/dev-product/<s5> snare=16 ^
     --run fingers data/dev-product/<f6> hihat=8,snare=8 --run sticks data/dev-product/<s6> hihat=8,snare=8 ^
     --run fingers data/dev-product/<f7> none       --run sticks data/dev-product/<s7> none ^
     --output data/dev-product/red-tip-comparison.json
   ```
   It reports, per mode:
   - correct / missed / false / wrong-zone / duplicate strikes against your counts;
   - tip continuity and loss gaps;
   - perception and frame time, FPS;
   - the app's software capture-to-audio-schedule latency (not the acoustic action-to-sound delay).
4. **Optional action-to-sound latency.** Tap a hard surface at a pad's top edge and record the tap and
   the speaker together (phone slow motion or one microphone). Measure about 10 taps per mode.
5. **Exposure.** At exposure -5 each frame integrates about 31 ms of motion, so fast tips smear. An
   exposure A/B in stick mode is an owner decision; this change leaves `camera_profile.exposure` as it is.

## 9. Limitations

- **Not yet measured with the camera:** real cap-point error, tip continuity, strike accuracy and
  latency. The paint's HSV under live exposure is known only from one probably tone-mapped photo. The
  live sessions suggest the paint reads less saturated than in the photo; the tuner exists for exactly
  this.
- **Fast motion:**
  - A long exposure smears a fast tip. A saturated core keeps a bound track OBSERVED. Fainter streaks are
    WEAK (at most 4 frames), then not measured.
  - A streak never starts a track, and a blur position is mid-exposure, behind the true tip.
  - A blurred red cap over a teal wall turns grey: a synthetic 80 px streak on the photo's wall colour
    was not recovered at all.
- **Paint runs:** a run longer than about 2 cap lengths dilutes the region's seed share and can drop
  the tip (`OFF_COLOUR`). Lower `min_seed_fraction` in the tuner, or touch up the paint.
- **Reflections:** an outline cut by a large highlight is restored inside the hull. A highlight covering
  most of a cap is not red, so the cap can shrink or vanish for that frame.
- **Skin and red clothing:** a face touching a cap moves the point by up to about 2 px (synthetic). Red
  clothes, lips under warm strong light or red objects can still pass; use `ignore_regions` or raise
  `s_min`.
- **Identity:**
  - Touching or overlapping tips are one blob: reported ambiguous (not measured), and both strokes
    restart afterwards, so a hit at that instant can be missed rather than invented.
  - Labels are stable identities, not guaranteed anatomical hands.
  - With red clutter in view, binding waits until the sticks move, so the first stroke after start-up
    can be lost.
- **Compute:** about +0.4 to +0.7 ms p50 per real frame against the first version (B), and still about
  1/10 of the hand model.

## 10. Playing distance (revision 2026-10-16, evening)

> Superseded on 2026-10-17 by section 11 (the `redness` detector is now the default). The dark-paint mode
> below remains available with `detector: colour` and `dark_paint: true`; its measurements are kept as
> history.

The owner reported that tracking works only when the sticks are close to the camera. The evidence is the
recording `data/dev-product/dev-product-20261016-225435` (622 frames, `--record-frames`, exposure -5,
native 720p capture, owner at playing distance) and the live session `-225536`.

### 10.1 Cause (measured, not guessed)

- **Colour, not size, is what fails.**
  - Cap pixels at 64 labelled caps: hue (signed) −61…−9 (median −34), S 52-144 (median 102), V 27-58
    (median 36).
  - The red seed floors (H ≤ 4 or ≥ 170, S ≥ 145, V ≥ 60) pass **0.3 %** of them.
  - The caps receive too little light at that distance, and the room's teal ambient light pushes the dark
    paint toward magenta. Close to the camera the paint is lit and reads red (the 2026-10-16 photo:
    H ≈ −1, S ≈ 190, V 117-246).
- **Size is secondary.** The caps are about 11 px across (~90 px², 640 × 480) and carry a white highlight.
  At that size even a well-lit cap clears the 30 px² floor.
- **The red signal is about 10 levels.** Cap R−G has a median of 10, against 2 for the dark shaft. The
  shaft, shirt, hair and shadows are just as dark.
- **The camera cannot simply be brightened.** Gain 8 doubles brightness and noise alike
  (`camera-quality-native-720p.md`), and exposure -4 drops to about 16 FPS (`camera-brightness.md`).
- **A second cause, in the live session `-225536`:** both slots sat on blobs clipped by the bottom edge
  of the frame (hands, sofa), at (0.8, 1.0) for LEFT in 1055 frames and (0.1, 1.0) for RIGHT. A clipped
  blob is never measured, so the slots were blocked.

### 10.2 Changes

| Change | Default? | What |
|---|---|---|
| Clipped tracks never take a slot | **on** | A blob touching the ROI border may continue a bound track as `CLIPPED` (not measured) but never binds a free slot or is adopted by a coasting one. |
| Dark-paint pass | **off** (`dark_paint: true` to enable) | Pixel band signed hue −60…+5, S ≥ 60, V 20-110, R−G ≥ 6. Blob averages: hue ≤ −20, R−B ≤ 4, S ≥ 85, V ≥ 32, area 15-250 px², elongation ≤ 3.5. A cap merged with the dark upper shaft is cut free at the region's wider end. |
| Dark births | with the pass | A dark blob starts a track only with a bright surround (≥ 65 % of 16 directions: the stick held up) and after **4** consecutive frames. Once bound it is followed anywhere (in front of the shirt too). |
| `DARK` evidence | with the pass | State `DARK`, reason `RED_TIP_DARK`, confidence 0.8 (VALID). A prediction is still never a measurement. |
| Diagnostics | on | Live view (`D`): violet rings = dark-paint candidates with their context share (`ctx`), grey rings with the reject reason (`OFF` / `LARGE` / `LONG`), slot states incl. `DARK`. |
| `--calibrate-dark LABELS` | tool | `scripts/tune_red_tips.py` derives a dark profile from labelled caps (pixel band from percentiles; blob limits by grid search, recall minus 0.3 × non-cap blobs per frame). |

### 10.3 Evidence (offline; real frames; labels from the recording)

- **Labels:** 64 cap centres on 61 frames of `-225435`, saved in the session folder as
  `red-tip-labels.{all,calib,test}.json`.
  - They come from a colour-independent silhouette rule: the dark rounded head at the top of a stick
    against the wall, with a bright surround above.
  - **Every crop was checked visually by the assistant. They were not clicked by the owner.**
  - Only caps against the wall are labelled, so caps in front of the body are not scored, and a measured
    tip on an unlabelled cap counts as "near no label".
- **Split:** the dark defaults were measured on frames sampled across the whole recording (in-sample).
  `test` = frames ≥ 200 (28 caps); `calib` = frames < 200 (36 caps), used only by `--calibrate-dark`.

| Recording `-225435` | Caps measured (test) | Caps measured (all) | Error p50 / p95 / max | Identity swaps (all) | Measured share L / R | ms p50 / p95 |
|---|---|---|---|---|---|---|
| Default (red only) | **0 / 28** | 0 / 64 | – | – | 0 % / 0 % | 2.8 / 4.6 |
| `dark_paint: true` | **23 / 28** | 43 / 64 | 1.8 / 4.6 / 5.1 px | 2 | 55 % / 78 % | 9.7 / 15.0 |
| `--calibrate-dark` on the calib half (weight 0.3) | 15 / 28 | 17 / 64 | 2.1 px p50 | 0 | – | – |

- **Detector alone** (no tracker), all 64 labels, dark mode: 55 / 64 caps found within 6 px, error p50 1.9
  px, about 2.9 other dark blobs per frame.
- **Loss gaps** (dark mode): p50 1 frame, p95 7-9 frames, max 50 frames.
- **What still goes wrong**, seen in `v3-distance/distance-dark-test/contact-sheet.jpg`:
  - The **left** stick's cap stands in front of a darker part of the wall and is found less often.
  - A slot sometimes sits on the purple blanket, the yellow cloth or a hand at the bottom of the frame
    (15 measured tips near no label on the test frames, some of them unlabelled caps).
  - Weak re-detection can slide onto a hand.
- **Unpainted captures** (`data/dev-captures`), dark mode on:
  - Dark candidates appear (frames with candidates 4 / 276 / 0 / 0 / 49), but **no track was ever bound**
    (0 binds): nothing measured, nothing struck.
  - Cost there is 4.8-8.5 ms p50.
- **Default path unchanged:**
  - 0 false frames on all five captures;
  - the synthetic suite matches the perfect-tip pipeline in all 5 cases;
  - the fingertip replays are identical to section 5 (243/3/6, 244/2/4, 141/37/10, 174/4/0);
  - the photo is unchanged, with or without dark mode.
- **Cost:** dark mode adds about **7 ms p50** per frame (about 9.5 against 2.5 ms; the hand model is
  27 ms).

Outputs: `experiments/pre-participant/20261016-red-tip/v3-distance/` (git-ignored; `tree-status.txt`
records the working tree).

### 10.4 What to do (owner)

**1. Recommended: light the sticks.** Put a lamp or desk light in front of you, slightly above the camera
and aimed at where the sticks play. Then record at your playing distance:

```
.\play-spacedrums.ps1 --demo --red-tips --record-frames --max-seconds 30
python scripts\analyze_red_tips.py frames data\dev-product\<session> --output experiments\red-tip-lit --contact-sheet 12
```

If the yellow crosshairs sit on both caps in `experiments\red-tip-lit\contact-sheet.jpg`, play
normally: `.\demo-sticks-spacedrums.ps1`.

**2. Dim room fallback, opt-in:**

```
python scripts\tune_red_tips.py data\dev-product\<session> --no-window --set dark_paint=true --save --output configs\red-tip.tuned.yaml
.\demo-sticks-spacedrums.ps1 --stick-tip-config configs\red-tip.tuned.yaml
```

- Raise each stick briefly against a lighter background at the start: a dark cap needs that context, and
  4 frames, to be picked up.
- Watch for `DARK` in the slot labels.

**3. Verify on your own footage** (cap-point error, detection rate, identity):

```
python scripts\tune_red_tips.py data\dev-product\<session> --label --label-every 10
python scripts\analyze_red_tips.py frames data\dev-product\<session> --labels data\dev-product\<session>\red-tip-labels.json --stick-tip-config configs\red-tip.tuned.yaml --output experiments\red-tip-accuracy
```

**Still PENDING (live):**
- detection and identity at playing distance with the lamp;
- strikes against counted ground truth (section 8);
- reacquisition after crossings and occlusions in real play;
- FPS with dark mode on.

The recording `-225435` has no strikes, crossings or occlusions worth scoring.

## 11. Revision 2026-10-17: caps by local redness, verified and tracked by evidence

**Status:** implemented and measured **offline** on labelled real recordings. **Live success is not
claimed:** live detection, unique FPS and strike counts are PENDING the owner's run (section 11.7).

### 11.1 Root causes (measured on labelled real recordings)

**Labels.**
- Four owner recordings at playing distance (exposure -5, teal room light): `dev-product-20261016-225435`,
  `-20261017-005436`, `-005615` and `-005812`, about 580-620 frames each.
- Every 12th-16th frame was labelled **by the assistant** from zoomed frames, and the files say so. 239
  visible caps.
- Blurred or hidden caps are marked `uncertain` and not scored.
- Close-range balls (24-55 px radius) carry their radius. A point within `max(12, r / 2)` px of the
  centre counts as found.
- `225435` labels only the caps against the wall (`"complete": false`), so its false-point counts are not
  evidence.
- The owner can correct every file with `scripts/tune_red_tips.py <session> --label`.

| # | Cause | Evidence |
|---|---|---|
| 1 | **The colour detector loses the caps at detection.** The caps are dark (V median 37-52) and magenta-shifted (hue down to -15 OpenCV units). `v_min` 60 rejects 58-75 % of cap pixels, and the hue band misses the rest. | "No candidate at the cap" for 71/72, 40/41, 49/55 and 64/64 labelled caps. Coverage 0-11 % (table 11.4). |
| 2 | **Dark-paint mode measures the wrong things.** Its wide band also passes hands, cloth and the frame bottom. | 52 of 55 measured points false on 005615, 40 of 44 on 005812. |
| 3 | **Pixel colour cannot separate paint from skin in this light.** | The best relaxed colour band reached ~60 % recall with 144 false frames on the unpainted `data/dev-captures`. |
| 4 | **Tracker rules built for bright caps fail here.** | Slots stuck on border-clipped junk. The motion deferral blocked caps held still. Weak re-detection walked onto skin (`WEAK_FRAMES` 570). |
| 5 | **Stick geometry is not a reliable gate.** The plan's stick-first design failed its own declared gate. | Shaft-end hypotheses (LSD edge pairs) reached 49-66 % of labelled caps, with ~10 hypotheses per frame and 8-13 ms. |
| 6 | **Where on the cap.** Highlights carve holes, stick B's neck is painted red for 25-45 px, and close-range balls are 50-110 px wide. | Points 20-40 px off on painted necks and big balls before the ball-centre and same-structure rules. |

**What does separate a cap is local contrast:** a small blob redder than its surround. A difference of
Gaussians of `min(R-G, R-B+12)` puts 94 % of the labelled caps among the 12 strongest candidates, usually
first or second.

### 11.2 Architecture and why

- **Detector** (`stick/red_tip_caps.py`, `detector: redness`, now the default).
  - **Candidates:** DoG peaks of the redness map at half resolution. Each peak grows into its region,
    with the level raised until the region closes.
  - **The point** is the centre of the region's largest inscribed circle: the ball. Highlights are filled;
    the neck and paint runs are narrower. For small regions the point is the DoG peak.
  - **One stick end:** candidates joined by a red path within 60 px are one end (`SAME_CAP`), and the
    widest part is kept.
  - **Clipping:** a ball cut by the border is `clipped`.
  - **Why:** it is the only candidate source that reached the caps at playing distance (cause 1, the
    finding below the table).
- **Verifier** (`CapVerifier`). A logistic score over eight region features:
  - DoG response and relative response;
  - redness contrast to a ring around the region;
  - brightness and saturation;
  - highlight;
  - `orange` = max(0, hue) and `blueness` = max(0, -hue).

  It is a standardised linear model with L2 = 1, written in NumPy, with no new dependency.
  - **Why linear:** on held-out recordings it matched LightGBM (and beat it on 005436), and it is a dot
    product (no per-call overhead).
  - **Why two hue terms:** a single hue term was fitted with the *wrong sign*, because the labelled junk
    was mostly bluish. It then rated skin as cap-like (281-349 measured frames on the unpainted
    captures). Splitting the term penalises orange explicitly: 0 frames.
  - **Coefficients:** the built-ins are fitted on all labelled frames; `fit-verifier` refits them.
- **Tracker** (`stick/red_tip_evidence.py`). One frame's quality flickers, so decisions use **evidence**,
  a running average of the quality.
  - **Measured** (`OBSERVED`) only with enough evidence and quality in the current frame; otherwise
    `LOW_EVIDENCE`, which is shown but never strikes.
  - **Stillness** lowers a track's slot rank, never its measurement, so a stick held still strikes at
    once. A track that never moved yields to the first moving tip.
  - **Adoption:** a coasting slot adopts a tip that reappears within reach after a short dropout. The
    stroke continues unless the other stick is unseen too.
  - **Blur:** the verifier learned still caps and scores a strike-speed streak near 0, so a tip measured
    within 0.2 s continues on it as `WEAK` (0.75, at most 4 frames, only while moving). `WEAK` never
    starts a measurement. A stroke leaving rest may take a candidate within twice its gate.
  - **Ambiguity:** after a merge, each slot returns to the side it was last measured on, and both strokes
    restart.
  - **Predictions** never carry coordinates.
- **Unchanged:**
  - contracts and MARKER labelling;
  - the decision pipeline, calibration and audio;
  - HAND mode and its configuration;
  - the camera paths.

  `detector: colour` keeps the previous detector and tracker.

### 11.3 Protocol (pre-declared in the plan; deviations stated)

- **Held-out split:** the verifier is fitted on the **first half** of each recording's labelled frames
  (`fit-verifier --first-half`) and scored on the **second half** (`frames --label-half second`). Old and
  new detectors run on identical frames.
- **Cross-recording:** leave-one-recording-out verifiers on all labels show how it generalises to an
  unseen session.
- **Deviation (label coverage):** labels are sampled frames, so "longest gap" and "reacquisition" come from
  all frames (slot measured or not), not from per-frame truth.
- **Deviation (tuning on the held-out halves):** the design (features, tracker rules) was iterated on these
  recordings, including the held-out halves, so the numbers are development evidence, not an independent
  test.

### 11.4 Before / after on identical frames

Outputs are in `experiments/pre-participant/20261016-red-tip/v6-final/` (git-ignored). Times are a
separate interleaved run of the three estimators on the same 340 frames of each recording.

| Recording (second half) | Old default (colour) | Old dark (`dark_paint`) | **New (redness)** |
|---|---|---|---|
| 225435 | 0/34 | 23/34; 19 of 42 points unmatched | **28/34 (82 %)**, A 27/27, B 1/7 |
| 005436 | 6/26 | 6/26 | **21/26 (81 %)**, A 10/12, B 11/14 |
| 005615 | 0/38 | 1/38; 27 of 28 points false | **28/38 (74 %)**, A 13/19, B 15/19 |
| 005812 | 1/17 | 1/17; 23 of 24 points false | **13/17 (76 %)**, A 2/5, B 11/12 |
| **All** | **7/115 (6 %)** | **31/115 (27 %)** | **90/115 (78 %)** |

| New, second halves | 225435 | 005436 | 005615 | 005812 |
|---|---|---|---|---|
| Error p50 / p95 px | 0.9 / 1.7 | 1.6 / 9.6 | 2.9 / 15.6 (*) | 1.6 / 4.0 |
| False / measured | (labels incomplete) | 1 / 24 | 8 / 37 (*) | 0 / 14 |
| Identity switches | 0 | 2 | 2 | 3 |
| Longest unmeasured run L / R (frames) | 18 / 25 | 9 / 15 | 15 / 14 | 64 / 36 |
| Measured share L / R | 80 / 83 % | 84 / 83 % | 80 / 78 % | 69 / 58 % |

(*) The 9 "false" points on the fully labelled recordings break down as follows:
- **5 on the ball but off-centre:** close-range caps of 72-110 px, where the labelled centre is coarse.
- **1 on stick B's painted neck** (005615 frame 348).
- **3 off the cap:** 2 `WEAK` continuations onto a nearby blob, and 1 hand (005436 frame 384).

That makes **3 of 75 (4 %) measured points truly off the cap**. Close-range matches also inflate 005615's
error p95.

**Identity switches:** all 7 are re-identifications after a loss, each announced by an identity reset.
An earlier version of this paragraph called 2 of them silent swaps; that came from a looser test, and
section 12.1 gives the precise definition and the analysis of every event.

**Gaps:** the longest unmeasured runs are stretches where a stick leaves the frame or sits dark at its
edge.

| Leave-one-recording-out (all labels) | 225435 | 005436 | 005615 | 005812 | All |
|---|---|---|---|---|---|
| Caps found | 56/64 | 41/56 | 56/72 | 34/41 | **187/233 (80 %)** |
| False / measured | (incomplete) | 17/61 | 11/69 | 5/40 | 33/170 |

The 005436 hands are the case an unseen room exposes: the other recordings hold almost no red-looking
hands.

| Check | Result |
|---|---|
| Unpainted `data/dev-captures` (8 captures, 2,732 frames, shipped default) | **0 measured frames** (the pre-declared rule) |
| Synthetic self-test, photo-size and small tips | every case matches the ideal-tip pipeline (the one `non-strikes` "false" is also made by the ideal pipeline) |
| Owner photo (`--scale 0.6667`) | both caps measured from the second frame |
| `replay-fingertips` 015648 (246 strikes), blur 0.9 / none | 242 / 239 matched, 13 / 13 extra (colour v3: 243 / 244, 6 / 4 extra) |
| `replay-fingertips` 003327 (178 strikes), blur 0.9 / none | **154** / 173 matched, 9 / 1 extra (colour v3: 141 / 174) |
| Per-frame cost p50 (p95), interleaved, 3 recordings | old default 2.5-4.0 ms, old dark 7.7-12.2 ms, **new 8.8-10.4 ms (11-12 ms)**: +4.9 to +7.9 ms |

**Against the pre-declared targets** (offline):
- **Met:**
  - error p50 ≤ 3 px;
  - added cost ≤ +8 ms;
  - 0 false frames on the unpainted captures;
  - the synthetic suite.
- **Not met:**
  - coverage ≥ 85 % per stick (78 % overall; stick B on 225435 and stick A on 005812 are low);
  - false ≤ 2 % (4 % truly off the cap);
  - 0 identity switches;
  - longest gap ≤ 10 frames;
  - p95 ≤ 8 px on two recordings.
- **Reacquisition:** within 3 frames in the synthetic tests; not measurable from sampled labels.

### 11.5 Tests

`tests/stick/test_red_tip_evidence.py` (SYNTHETIC) covers:
- small dark magenta and dark red caps on the teal wall;
- the ball centre at four orientations with a painted neck, a shaft and a highlight;
- a blurred fast stroke, and a strike-speed streak continuing as `WEAK` up to the limit;
- exposure changes;
- a hidden tip, which is never measured and returns to its slot;
- adoption after a dropout without a stroke restart;
- crossing tips, and tips meeting (ambiguous, then reset, never swapped);
- a static red lamp, which never keeps a slot;
- skin and speckles, which are never measured;
- one stick only;
- identity memory for a returning tip;
- leaving and re-entering the frame;
- a long gap, which never re-emits a stale point;
- a single-frame red flash, which is never measured;
- records and labelling;
- verifier fit and validation, and settings validation.

Other changes:
- The colour-path tests pin `detector: colour`.
- The play tests (strikes vs perfect measurements, MARKER logs, **HAND modes never build the red-tip
  perception**) run on the new default.
- `tests/ui/test_red_tip_overlay.py` checks the cap outline and the untrusted-tip ring.

### 11.6 Live debug view

`D` toggles the diagnostics view (section 4). It shows:
- the cap outline and centre, and `q` per candidate;
- `L` / `R` slot identities with the track id;
- states: `OBS` / `WEAK` (filled dot), and `LOW` / `AMBIG` / `EDGE` (orange ring), `PRED` (thin ring);
- the rejects `SAME` / `IGN`;
- the `REDNESS` inset.

### 11.7 Owner commands and what remains PENDING

```
.\demo-sticks-spacedrums.ps1                                  # play; D = diagnostics
.\play-spacedrums.ps1 --demo --red-tips --record-frames --max-seconds 30
python scripts\tune_red_tips.py data\dev-product\<session> --label --label-every 10
python scripts\analyze_red_tips.py frames data\dev-product\<session> --labels data\dev-product\<session>\red-tip-labels.json --output experiments\red-tip-check
python scripts\analyze_red_tips.py fit-verifier data\dev-product\<session1> data\dev-product\<session2> --output experiments\my-verifier
.\demo-sticks-spacedrums.ps1 --stick-tip-config experiments\my-verifier\verifier.yaml
python scripts\compare_play_sessions.py ...                   # fingers vs sticks strike counts (section 8)
.\play-spacedrums.ps1 --fingers                               # HAND mode, unchanged
```

**PENDING (owner, live):**
- detection and identity in real play;
- unique FPS with the new detector;
- strikes against counted ground truth;
- a lit session (a lamp still helps: everything above was measured in dim teal light);
- labels made by a person instead of the assistant.

**Limitations:**
- The verifier is learned from assistant labels of one room, light and pair of sticks.
- Hands that look red can still win a slot for a few frames, and `WEAK` frames can land on a nearby blob
  (at most 4 frames).
- Stick B's painted neck can win over the ball when the ball is dim.
- Close-range balls are measured on the ball but not at its centre.
- A cap at the frame edge is `CLIPPED` until it is fully visible.

## 12. Follow-up 2026-10-17: the acceptance failures of section 11

The owner asked for five open failures to be investigated before any further tuning: identity switches,
long gaps, extra strikes, cap-centre accuracy and edge handling. The current implementation was kept as the
baseline.

**Method.** Every change was rerun on the same regression set: the four labelled recordings (first halves
= development, second halves = held out, scored with the verifier fitted on first halves; no label was
changed), the eight unpainted captures, the four fingertip replays and the synthetic suite. Scratch tools
classify every switch, gap and extra strike.

The replay tool now writes `strikes.json` (every strike of both pipelines; each extra or missed one with
the nearest strike of the other pipeline, and the slot states, track ids and resets before it) and counts
identity `flips` (frames where the slots' hand assignment against the fingertips changes).

### 12.1 Identity switches

**A precise definition first.** A *silent swap* is one track, in one slot, measuring two different sticks
at consecutive labelled frames with no identity reset of that slot in between. Only then can a stroke
continue across a change of stick.

- **Section 11's count of "2 silent swaps" used a looser test,** so it was wrong. That test counted any
  stick that changed slot while its old slot kept its track. By the precise definition **the baseline has
  0 silent swaps** in both halves.
- **Its 7 held-out switches are re-identifications,** each with an identity reset. Strokes restart, which
  is the "mark it uncertain" behaviour.

| Baseline switch (held-out) | Cause |
|---|---|
| 005436 A 432 to 480, B 400 to 480 | The sticks cross physically; both tracks are lost; rebinding puts them in the other slots. |
| 005615 A 444 to 552, B 480 to 492 | Close range: two candidates on one 110 px ball (merge reach was fixed at 60 px); the duplicate fills the free slot. |
| 005812 B 416 to 432, 432 to 448, 464 to 528 | A WEAK continuation follows a fast stroke away from the cap; the cap is reborn and takes the free slot (identity memory was not consulted). |

The labels were checked at each event and are consistent: the sticks really cross in 005615 (290-300 and
324-348).

**Four tracker changes were tried, each on the whole set. None is adopted:**

| Variant | Held-out caps / false / switches (silent) | Dev caps / switches (silent) | Replay flips |
|---|---|---|---|
| Baseline | 90 / 9 / 7 (0) | 97 / 5 (0) | 8 |
| Identity memory has priority in binding | 91 / 14 / 9 (**1**) | 96 / 3 (0) | 7 |
| + evidence-weighted association + anisotropic gate | 92 / 8 / 7 (0) | 98 / 8 (0) | – |
| Association changes only | 93 / 11 / 11 (0) | 96 / 5 (0) | 9 |
| + merged-candidate ambiguity | 90 / 11 / 9 (0) | 101 / 4 (**1**) | 8 |

They moved switches around rather than removing them, and two of them introduced a real silent swap. The
binding logic therefore stays as it was.

**One silent swap remains possible:** a crossing in which only one stick is tracked and that stick reverses
inside a blur. Its WEAK continuation can then follow the other stick. It was seen once in a development
run, not with the final code.

### 12.2 Long gaps

**The longest gaps are mostly a stick out of view.** In every gap of 9 frames or more, the labelled frames
inside show no visible cap left unmeasured, except:
- **first sightings,** measured from their second frame by design (a one-frame red flash is never
  measured);
- **one cap cut by the top edge** (12.5);
- **the dim magenta caps of 225435** (verifier quality 0.07-0.5), which the evidence gate holds back
  (`LOW_EVIDENCE`).

Lowering the gate for them would let hands in again, so it is not changed. A stick returning near where its
slot last measured it is bound on its first frame (identity memory). In the synthetic tests reacquisition
takes at most 3 frames.

### 12.3 Extra strikes

On replay 015648 every one of the baseline's 13 extra strikes happened while the slot was steadily
OBSERVED on one track, with no reset and no WEAK frame. They were not an identity or tracking problem:
- 9 were second strikes 4-11 frames after a real one in the same zone;
- 4 were in a zone with no fingertip strike nearby.

**The cause was point jitter.** For small caps the cap point was the half-resolution centre, which moves
in 2 px steps.

| On replay frames (synthetic tips at recorded positions) | Colour detector | Baseline redness | **Final** |
|---|---|---|---|
| Point error p50 / p95 | 0.14 / 0.31 px | 0.44 / 1.29 px | **0.20 / 0.47 px** |
| Frame-to-frame change of the error p50 / p95 | 0.18 / 0.46 px | 0.65 / 1.71 px | **0.30 / 0.70 px** |

**Fix.** A slot's measured tip is now re-measured at full resolution after tracking
(`CapDetector.refined`): the inscribed-circle centre of the pixels above the mid level inside the region.
Association still uses the half-resolution point.

Refining every candidate cost 3.8 ms. Refining only candidates with a high score reintroduced the jitter on
blurred strokes (extras 3 -> 11), so only the two slot tips are refined.

| Replay: matched / missed / extra strikes | Baseline | **Final** |
|---|---|---|
| 015648, blur 0.9 | 242 / 4 / 13 | 239 / 7 / **7** |
| 015648, no blur | 239 / 7 / 13 | **243 / 3 / 1** |
| 003327, blur 0.9 | 154 / 24 / 9 | **158 / 20 / 4** |
| 003327, no blur | 173 / 5 / 1 | 172 / 6 / **0** |

The remaining extras are mostly a second strike 3-14 frames after a real one in the same zone, around
stroke reversals in heavy blur. They are a decision-pipeline sensitivity, and no strike threshold was
changed.

### 12.4 Cap centre

- **One stick end** (`SAME_CAP` merge). When two candidates of one red structure lie apart along the stick,
  the cap is the end beyond which the image is clearly less red: wall beyond the ball, wooden shaft beyond
  the neck.
  - **Owner frame 005615 348:** the point moves from the painted neck (564, 114) to the ball (564, 87).
  - **Gated at quality ≥ 0.5 for both parts.** A synthetic warm-lit shaft reads red. Ungated, the rule
    once dropped the cap region for a shaft piece (quality 0.39); a test now covers this.
- **A version that re-pointed every elongated region at its stick end was tried and removed.** It fixed a
  synthetic scene but cost 3 caps in each half and raised 005615's p95 to 16.9 px.
- **Pieces of one ball** (close range: shading and highlights cut it apart): the merge reach scales with
  the ball (2.5 radii for radius ≥ 20 px), and the point is the centre of the pieces' union.
- **Big round regions** (inscribed radius ≥ 15 px, hull ≥ half its enclosing circle) use the convex
  hull's centroid. This rule was chosen on the development caps only.

| Close-range caps (labelled radius 24-55 px): centre error | Baseline | **Final** |
|---|---|---|
| Development half, 8 caps (radius 24-35 px): mean / median | 7.4 / 5 px | **4.3 / 4 px** |
| Held-out half, 11 caps (radius 27-55 px): mean / median | 24.0 / 19 px | 22.9 / 17 px |
| Extra candidates on one close-range ball | 3 | 2 |

**Limitation:** the biggest balls (radius 50-55 px, a stick about 15 cm from the lens) still break into
rim pieces 28-45 px from the centre. The redness blob scales do not cover a ball that size. The point is on
the ball, not at its centre.

### 12.5 Edge handling

Only **2 of 233** labelled caps lie at the frame edge (within max(15 px, radius)), plus 2 unscored
uncertain caps. One is a cap at y = 4 (a quality 0.03 candidate 3.6 px away); the other is a 50 px ball cut
by the top edge (no candidate).

These recordings cannot show that a cut cap's point is accurate, so cut caps stay `CLIPPED`: seen, never
measured, never a strike. No measurement is invented at the edge.

Measuring this needs a recording that sweeps both sticks slowly out of and back into each edge, labelled
with `--label`.

### 12.6 Final numbers (same frames, `--label-half second` with the first-half verifier)

| | Baseline (section 11) | **Final** |
|---|---|---|
| Held-out caps found (A / B per recording in the text) | 90/115 | **92/115** |
| Development caps found | 97/118 | **101/118** |
| False points on fully labelled recordings (held-out) | 9/75 | **7/74** |
| Identity switches held-out / dev (silent swaps) | 7 / 5 (0) | 12 / 3 (0) |
| Longest unmeasured run, frames (mostly out of view, 12.2) | 64 | 64 |
| Replay strikes matched / missed / extra (4 runs) | 808 / 40 / 36 | 812 / 36 / **12** |
| Replay identity flips (4 runs) | 8 | 8 |
| Unpainted captures, measured frames | 0 | 0 |
| Synthetic suite | all match | all match |
| Cost per frame p50, interleaved with the old colour default | 10.1 ms (+7.1) | 10.5 ms (+7.2) |

**Per held-out recording (final):**

| Recording | Caps found | False | Switches | Error p50 / p95 |
|---|---|---|---|---|
| 225435 | 29/34 | (labels incomplete) | 3 | 1.0 / 2.8 px |
| 005436 | 20/26 | 2/24 | 2 | 1.7 / 6.0 px |
| 005615 | 30/38 | 5/36 | 2 | 2.4 / 12.9 px (close range) |
| 005812 | 13/17 | 0/14 | 5 | 1.6 / 3.7 px |

**Still unmet (section 11.4 targets):**
- coverage ≥ 85 % per stick;
- 0 identity switches;
- gaps ≤ 10 frames.

### 12.7 Live validation (owner, about 10 minutes)

Nothing here is a live result. Run this once, in the usual room and light:

1. `.\demo-sticks-spacedrums.ps1` and press `D`.
   - Hold both sticks up and still for 5 s: two filled dots, `L#.. OBS` and `R#.. OBS`, sitting on the
     balls.
   - Move each stick alone, then cross them twice: an `AMBIG` ring or a brief `LOW` is fine; a dot on a
     hand, the shaft or the wall is not.
   - Note the `RED .. ms` value on the HUD.
2. Record 30 s of normal playing:
   `.\play-spacedrums.ps1 --demo --red-tips --record-frames --max-seconds 30`
   - Count the hits you play aloud, or write them down per drum.
3. Score it offline:
   `python scripts\analyze_red_tips.py frames data\dev-product\<session> --output experiments\live-check --contact-sheet 12`
   - Look at `experiments\live-check\contact-sheet.jpg`: every filled dot must be on a ball.
   - Compare your hit count with `commits_by_drum` in `data\dev-product\<session>\report.json`.
4. Optional, for a stronger check: label every 10th frame (`python scripts\tune_red_tips.py
   data\dev-product\<session> --label --label-every 10`) and rerun step 3 with `--labels
   data\dev-product\<session>\red-tip-labels.json`, which reports coverage, false points and switches.
5. HAND mode is unchanged: `.\play-spacedrums.ps1 --fingers`.

Report the HUD ms, the counted versus committed hits, and any dot seen off a ball.
